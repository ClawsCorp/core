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
from src.models.revenue_event import RevenueEvent
from src.models.expense_event import ExpenseEvent

ORACLE_SECRET = "test-oracle-secret"


def _sign(secret: str, payload: str) -> str:
    return hmac.new(secret.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).hexdigest()


def _oracle_headers(path: str, body: bytes, request_id: str, *, method: str = "POST") -> dict[str, str]:
    timestamp = str(int(time.time()))
    body_hash = hashlib.sha256(body).hexdigest()
    payload = build_oracle_hmac_v2_payload(timestamp, request_id, method, path, body_hash)
    return {
        "Content-Type": "application/json",
        "X-Request-Timestamp": timestamp,
        "X-Request-Id": request_id,
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


def test_project_settlement_compute_and_public_read(_client: TestClient, _db: sessionmaker[Session]) -> None:
    with _db() as db:
        project = Project(project_id="proj_s_1", slug="proj-s-1", name="S1", status=ProjectStatus.active)
        db.add(project)
        db.flush()
        db.add(
            RevenueEvent(
                event_id="rev_1",
                profit_month_id="202602",
                project_id=project.id,
                amount_micro_usdc=2_000_000,
                tx_hash=None,
                source="test",
                idempotency_key="idem:rev:1",
                evidence_url=None,
            )
        )
        db.add(
            ExpenseEvent(
                event_id="exp_1",
                profit_month_id="202602",
                project_id=project.id,
                amount_micro_usdc=500_000,
                tx_hash=None,
                category="test_expense",
                idempotency_key="idem:exp:1",
                evidence_url=None,
            )
        )
        db.commit()

    compute_path = "/api/v1/oracle/projects/proj_s_1/settlement/202602"
    body = b""
    resp = _client.post(
        compute_path,
        content=body,
        headers=_oracle_headers(compute_path, body, "req-compute"),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["project_id"] == "proj_s_1"
    assert data["profit_month_id"] == "202602"
    assert data["revenue_sum_micro_usdc"] == 2_000_000
    assert data["expense_sum_micro_usdc"] == 500_000
    assert data["profit_sum_micro_usdc"] == 1_500_000

    public_path = "/api/v1/projects/proj_s_1/settlement/202602"
    resp = _client.get(public_path)
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["success"] is True
    assert payload["data"]["settlement"]["profit_sum_micro_usdc"] == 1_500_000

