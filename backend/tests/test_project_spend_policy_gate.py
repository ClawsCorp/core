from __future__ import annotations

import hashlib
import hmac
import json
import sys
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from src.core.config import get_settings
from src.core.database import Base, get_db
from src.core.security import build_oracle_hmac_v2_payload
from src.main import app

import src.models  # noqa: F401
from src.models.project import Project, ProjectStatus
from src.models.project_spend_policy import ProjectSpendPolicy
from src.models.project_update import ProjectUpdate

ORACLE_SECRET = "test-oracle-secret"


def _sign(secret: str, payload: str) -> str:
    return hmac.new(secret.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).hexdigest()


def _oracle_headers(path: str, body: bytes, request_id: str, *, idem: str, method: str = "POST") -> dict[str, str]:
    timestamp = str(int(time.time()))
    body_hash = hashlib.sha256(body).hexdigest()
    payload = build_oracle_hmac_v2_payload(timestamp, request_id, method, path, body_hash)
    return {
        "Content-Type": "application/json",
        "X-Request-Timestamp": timestamp,
        "X-Request-Id": request_id,
        "Idempotency-Key": idem,
        "X-Signature": _sign(ORACLE_SECRET, payload),
    }


@pytest.fixture(autouse=True)
def _isolate_settings_cache() -> None:
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture()
def _db() -> sessionmaker[Session]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    session_local = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    Base.metadata.create_all(bind=engine)
    return session_local


@pytest.fixture()
def _client(_db: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("ORACLE_HMAC_SECRET", ORACLE_SECRET)
    monkeypatch.setenv("ORACLE_REQUEST_TTL_SECONDS", "300")
    monkeypatch.setenv("ORACLE_CLOCK_SKEW_SECONDS", "5")
    monkeypatch.setenv("ORACLE_ACCEPT_LEGACY_SIGNATURES", "false")

    def _override_get_db():
        db = _db()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = _override_get_db
    client = TestClient(app, raise_server_exceptions=False)
    try:
        yield client
    finally:
        app.dependency_overrides.clear()


def test_oracle_expense_event_blocked_when_month_cap_exceeded(_client: TestClient, _db: sessionmaker[Session]) -> None:
    db = _db()
    try:
        project = Project(
            project_id="prj_1",
            slug="p1",
            name="P1",
            description_md=None,
            status=ProjectStatus.active,
            proposal_id=None,
            origin_proposal_id=None,
            originator_agent_id=None,
            discussion_thread_id=None,
            treasury_wallet_address=None,
            treasury_address=None,
            revenue_wallet_address=None,
            revenue_address=None,
            monthly_budget_micro_usdc=None,
            created_by_agent_id=None,
            approved_at=None,
        )
        db.add(project)
        db.flush()
        db.add(
            ProjectSpendPolicy(
                project_id=project.id,
                per_month_cap_micro_usdc=100,
                per_day_cap_micro_usdc=None,
                per_bounty_cap_micro_usdc=None,
            )
        )
        db.commit()
    finally:
        db.close()

    path = "/api/v1/oracle/expense-events"
    body_obj = {
        "profit_month_id": "202602",
        "project_id": "prj_1",
        "amount_micro_usdc": 150,
        "tx_hash": None,
        "category": "project_ops",
        "idempotency_key": "idem-exp-1",
        "evidence_url": None,
    }
    body = json.dumps(body_obj, separators=(",", ":"), sort_keys=True).encode("utf-8")

    resp = _client.post(path, content=body, headers=_oracle_headers(path, body, "req-1", idem="idem-1"))
    assert resp.status_code == 409
    assert resp.json()["detail"] == "project_spend_policy_per_month_exceeded"


def test_oracle_expense_event_allows_when_under_cap(_client: TestClient, _db: sessionmaker[Session]) -> None:
    db = _db()
    try:
        project = Project(
            project_id="prj_2",
            slug="p2",
            name="P2",
            description_md=None,
            status=ProjectStatus.active,
            proposal_id=None,
            origin_proposal_id=None,
            originator_agent_id=None,
            discussion_thread_id=None,
            treasury_wallet_address=None,
            treasury_address=None,
            revenue_wallet_address=None,
            revenue_address=None,
            monthly_budget_micro_usdc=None,
            created_by_agent_id=None,
            approved_at=None,
        )
        db.add(project)
        db.flush()
        db.add(
            ProjectSpendPolicy(
                project_id=project.id,
                per_month_cap_micro_usdc=200,
                per_day_cap_micro_usdc=None,
                per_bounty_cap_micro_usdc=None,
            )
        )
        db.commit()
    finally:
        db.close()

    path = "/api/v1/oracle/expense-events"
    body_obj = {
        "profit_month_id": "202602",
        "project_id": "prj_2",
        "amount_micro_usdc": 150,
        "tx_hash": None,
        "category": "project_ops",
        "idempotency_key": "idem-exp-2",
        "evidence_url": None,
    }
    body = json.dumps(body_obj, separators=(",", ":"), sort_keys=True).encode("utf-8")

    resp = _client.post(path, content=body, headers=_oracle_headers(path, body, "req-2", idem="idem-2"))
    assert resp.status_code == 200
    assert resp.json()["success"] is True

    db = _db()
    try:
        update = db.query(ProjectUpdate).first()
        assert update is not None
        assert update.update_type == "expense"
        assert update.source_kind == "oracle_expense_event"
        assert update.source_ref == "idem-exp-2"
    finally:
        db.close()


def test_oracle_expense_event_allows_long_request_idempotency_key(_client: TestClient, _db: sessionmaker[Session]) -> None:
    db = _db()
    try:
        project = Project(
            project_id="prj_3",
            slug="p3",
            name="P3",
            description_md=None,
            status=ProjectStatus.active,
            proposal_id=None,
            origin_proposal_id=None,
            originator_agent_id=None,
            discussion_thread_id=None,
            treasury_wallet_address=None,
            treasury_address=None,
            revenue_wallet_address=None,
            revenue_address=None,
            monthly_budget_micro_usdc=None,
            created_by_agent_id=None,
            approved_at=None,
        )
        db.add(project)
        db.flush()
        db.add(
            ProjectSpendPolicy(
                project_id=project.id,
                per_month_cap_micro_usdc=500,
                per_day_cap_micro_usdc=None,
                per_bounty_cap_micro_usdc=None,
            )
        )
        db.commit()
    finally:
        db.close()

    long_idem = "x" * 240
    path = "/api/v1/oracle/expense-events"
    body_obj = {
        "profit_month_id": "202602",
        "project_id": "prj_3",
        "amount_micro_usdc": 150,
        "tx_hash": None,
        "category": "project_ops",
        "idempotency_key": long_idem,
        "evidence_url": None,
    }
    body = json.dumps(body_obj, separators=(",", ":"), sort_keys=True).encode("utf-8")

    resp = _client.post(path, content=body, headers=_oracle_headers(path, body, "req-3", idem="idem-3"))
    assert resp.status_code == 200
    assert resp.json()["success"] is True

    db = _db()
    try:
        update = db.query(ProjectUpdate).filter(ProjectUpdate.source_kind == "oracle_expense_event").first()
        assert update is not None
        assert update.idempotency_key is not None
        assert len(update.idempotency_key) <= 255
        assert update.source_ref == long_idem[:128]
    finally:
        db.close()
