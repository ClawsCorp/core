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
from src.core.security import build_oracle_hmac_v2_payload, generate_agent_api_key, hash_api_key
from src.main import app

import src.models  # noqa: F401
from src.models.agent import Agent
from src.models.bounty import Bounty, BountyFundingSource, BountyStatus
from src.models.expense_event import ExpenseEvent
from src.models.project import Project, ProjectStatus
from src.models.project_capital_event import ProjectCapitalEvent
from src.models.project_capital_reconciliation_report import ProjectCapitalReconciliationReport
from src.models.project_update import ProjectUpdate

ORACLE_SECRET = "test-oracle-secret"


def _sign(secret: str, payload: str) -> str:
    return hmac.new(secret.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).hexdigest()


def _oracle_headers(path: str, body: bytes, request_id: str, *, idem: str) -> dict[str, str]:
    timestamp = str(int(time.time()))
    body_hash = hashlib.sha256(body).hexdigest()
    payload = build_oracle_hmac_v2_payload(timestamp, request_id, "POST", path, body_hash)
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
    monkeypatch.setenv("PROJECT_CAPITAL_RECONCILIATION_MAX_AGE_SECONDS", "3600")

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


def _seed_agent_and_project(db: Session) -> str:
    agent_id = "ag_cycle"
    api_key = generate_agent_api_key(agent_id)
    db.add(
        Agent(
            agent_id=agent_id,
            name="Cycle",
            capabilities_json="[]",
            wallet_address=None,
            api_key_hash=hash_api_key(api_key),
            api_key_last4=api_key[-4:],
        )
    )
    db.add(
        Project(
            project_id="prj_cycle_1",
            slug="cycle-1",
            name="Cycle Project",
            status=ProjectStatus.active,
        )
    )
    db.commit()
    return api_key


def _project_db_id(db: Session) -> int:
    project = db.query(Project).filter(Project.project_id == "prj_cycle_1").first()
    assert project is not None
    return project.id


def test_full_bounty_cycle_happy_path_with_reconciliation_gate(
    _client: TestClient,
    _db: sessionmaker[Session],
) -> None:
    with _db() as db:
        api_key = _seed_agent_and_project(db)

    # 1) Agent creates bounty.
    resp = _client.post(
        "/api/v1/agent/bounties",
        headers={"X-API-Key": api_key, "Idempotency-Key": "bounty:create:cycle:1"},
        json={
            "project_id": "prj_cycle_1",
            "funding_source": "project_capital",
            "title": "Implement thing",
            "description_md": "Details",
            "amount_micro_usdc": 1_000_000,
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    bounty_id = body["data"]["bounty_id"]

    # 2) Agent claims bounty.
    resp = _client.post(
        f"/api/v1/bounties/{bounty_id}/claim",
        headers={"X-API-Key": api_key},
        json={},
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["status"] == "claimed"

    # 3) Agent submits bounty with PR url + merge sha.
    resp = _client.post(
        f"/api/v1/bounties/{bounty_id}/submit",
        headers={"X-API-Key": api_key},
        json={"pr_url": "https://github.com/ClawsCorp/core/pull/999", "merge_sha": "deadbeef"},
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["status"] == "submitted"

    # 4) Oracle evaluates eligibility (all checks success).
    eligibility_path = f"/api/v1/bounties/{bounty_id}/evaluate-eligibility"
    eligibility_body = json.dumps(
        {
            "pr_url": "https://github.com/ClawsCorp/core/pull/999",
            "merged": True,
            "merge_sha": "deadbeef",
            "required_approvals": 1,
            "required_checks": [
                {"name": "backend", "status": "success"},
                {"name": "frontend", "status": "success"},
                {"name": "contracts", "status": "success"},
                {"name": "dependency-review", "status": "success"},
                {"name": "secrets-scan", "status": "success"},
            ],
        },
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    resp = _client.post(
        eligibility_path,
        content=eligibility_body,
        headers=_oracle_headers(eligibility_path, eligibility_body, "req-elig", idem="idem-elig"),
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["status"] == "eligible_for_payout"

    # 5) Mark paid is blocked until reconciliation exists and capital is sufficient.
    mark_paid_path = f"/api/v1/bounties/{bounty_id}/mark-paid"
    mark_paid_body = json.dumps({"paid_tx_hash": "0x" + "a" * 64}, separators=(",", ":"), sort_keys=True).encode("utf-8")
    resp = _client.post(
        mark_paid_path,
        content=mark_paid_body,
        headers=_oracle_headers(mark_paid_path, mark_paid_body, "req-paid-1", idem="idem-paid-1"),
    )
    assert resp.status_code == 200
    blocked = resp.json()
    assert blocked["success"] is False
    assert blocked["blocked_reason"] == "project_capital_reconciliation_missing"

    # 6) Insert reconciliation + capital, then mark paid succeeds.
    with _db() as db:
        pid = _project_db_id(db)
        db.add(
            ProjectCapitalEvent(
                event_id="pcap_in_1",
                idempotency_key="pcap:in:1",
                profit_month_id=datetime.now(timezone.utc).strftime("%Y%m"),
                project_id=pid,
                delta_micro_usdc=2_000_000,
                source="test_funding",
                evidence_tx_hash=None,
                evidence_url=None,
            )
        )
        db.add(
            ProjectCapitalReconciliationReport(
                project_id=pid,
                treasury_address="0x" + "1" * 40,
                ledger_balance_micro_usdc=2_000_000,
                onchain_balance_micro_usdc=2_000_000,
                delta_micro_usdc=0,
                ready=True,
                blocked_reason=None,
                computed_at=datetime.now(timezone.utc),
            )
        )
        db.commit()

    resp = _client.post(
        mark_paid_path,
        content=mark_paid_body,
        headers=_oracle_headers(mark_paid_path, mark_paid_body, "req-paid-2", idem="idem-paid-2"),
    )
    assert resp.status_code == 200
    paid = resp.json()
    assert paid["success"] is True
    assert paid["data"]["status"] == "paid"

    with _db() as db:
        bounty = db.query(Bounty).filter(Bounty.bounty_id == bounty_id).first()
        assert bounty is not None
        assert bounty.status == BountyStatus.paid
        assert bounty.funding_source == BountyFundingSource.project_capital
        assert db.query(ExpenseEvent).count() == 1
        # capital outflow is appended on mark-paid for project_capital funded bounties.
        assert db.query(ProjectCapitalEvent).filter(ProjectCapitalEvent.delta_micro_usdc < 0).count() == 1
        update = (
            db.query(ProjectUpdate)
            .filter(ProjectUpdate.source_kind == "bounty_paid", ProjectUpdate.source_ref == bounty_id)
            .first()
        )
        assert update is not None
        assert update.update_type == "expense"
