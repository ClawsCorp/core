from __future__ import annotations

import hashlib
import hmac
import json
import sys
import time
from datetime import datetime, timezone
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
from src.models.bounty import Bounty, BountyFundingSource, BountyStatus
from src.models.expense_event import ExpenseEvent
from src.models.project import Project, ProjectStatus
from src.models.project_capital_event import ProjectCapitalEvent
from src.models.project_capital_reconciliation_report import ProjectCapitalReconciliationReport

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

    # Keep reconciliation freshness gate permissive for tests.
    monkeypatch.setenv("PROJECT_CAPITAL_RECONCILIATION_MAX_AGE_SECONDS", "86400")

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


def test_bounty_mark_paid_is_idempotent_on_expense_and_capital_outflow(
    _client: TestClient, _db: sessionmaker[Session]
) -> None:
    # Seed a project with sufficient capital and a fresh strict-ready reconciliation.
    with _db() as db:
        project = Project(project_id="proj_1", slug="p1", name="P1", status=ProjectStatus.active)
        db.add(project)
        db.commit()
        db.refresh(project)

        db.add(
            ProjectCapitalEvent(
                event_id="pcap_seed_1",
                idempotency_key="cap:seed:1",
                profit_month_id="202602",
                project_id=project.id,
                delta_micro_usdc=10_000,
                source="seed",
                evidence_tx_hash=None,
                evidence_url=None,
            )
        )
        db.add(
            ProjectCapitalReconciliationReport(
                project_id=project.id,
                treasury_address="0x" + "1" * 40,
                ledger_balance_micro_usdc=10_000,
                onchain_balance_micro_usdc=10_000,
                delta_micro_usdc=0,
                ready=True,
                blocked_reason=None,
                computed_at=datetime.now(timezone.utc),
            )
        )

        bounty = Bounty(
            bounty_id="bty_1",
            idempotency_key=None,
            project_id=project.id,
            funding_source=BountyFundingSource.project_capital,
            title="B1",
            description_md=None,
            amount_micro_usdc=123,
            status=BountyStatus.eligible_for_payout,
            claimant_agent_id=None,
            claimed_at=None,
            submitted_at=None,
            pr_url="https://example.com/pr/1",
            merge_sha="deadbeef",
            paid_tx_hash=None,
        )
        db.add(bounty)
        db.commit()

    path = "/api/v1/bounties/bty_1/mark-paid"
    body = json.dumps({"paid_tx_hash": "0x" + "a" * 64}, separators=(",", ":"), sort_keys=True).encode("utf-8")

    r1 = _client.post(path, content=body, headers=_oracle_headers(path, body, "req-1", idem="idem-1"))
    assert r1.status_code == 200
    assert r1.json()["success"] is True
    assert r1.json()["data"]["status"] == "paid"

    r2 = _client.post(path, content=body, headers=_oracle_headers(path, body, "req-2", idem="idem-2"))
    assert r2.status_code == 200
    assert r2.json()["success"] is True
    assert r2.json()["data"]["status"] == "paid"

    with _db() as db:
        expenses = db.query(ExpenseEvent).filter(ExpenseEvent.idempotency_key == "expense:bounty_paid:bty_1").all()
        assert len(expenses) == 1

        capital_outflows = db.query(ProjectCapitalEvent).filter(ProjectCapitalEvent.idempotency_key == "cap:bounty_paid:bty_1").all()
        assert len(capital_outflows) == 1

