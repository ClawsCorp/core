from __future__ import annotations

import hashlib
import hmac
import json
import sys
import time
from datetime import datetime, timedelta, timezone
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
from src.models.audit_log import AuditLog
from src.models.bounty import Bounty, BountyFundingSource, BountyStatus
from src.models.project import Project, ProjectStatus
from src.models.project_revenue_reconciliation_report import ProjectRevenueReconciliationReport

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
    monkeypatch.setenv("PROJECT_REVENUE_RECONCILIATION_MAX_AGE_SECONDS", "3600")

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


def _seed_project_bounty(db: Session) -> Bounty:
    project = Project(
        project_id="prj_rev_gate_1",
        slug="rev-gate-prj",
        name="Revenue Gate Project",
        status=ProjectStatus.active,
    )
    db.add(project)
    db.flush()

    bounty = Bounty(
        bounty_id="bty_rev_gate_1",
        project_id=project.id,
        funding_source=BountyFundingSource.project_revenue,
        title="Revenue reconciliation gate",
        description_md=None,
        amount_micro_usdc=1_000_000,
        status=BountyStatus.eligible_for_payout,
    )
    db.add(bounty)
    db.commit()
    return bounty


def _insert_reconciliation(
    db: Session,
    *,
    project_id: int,
    ready: bool,
    delta_micro_usdc: int | None,
    computed_at: datetime,
) -> None:
    db.add(
        ProjectRevenueReconciliationReport(
            project_id=project_id,
            revenue_address="0x" + "2" * 40,
            ledger_balance_micro_usdc=10_000_000,
            onchain_balance_micro_usdc=10_000_000,
            delta_micro_usdc=delta_micro_usdc,
            ready=ready,
            blocked_reason=None if ready and delta_micro_usdc == 0 else "balance_mismatch",
            computed_at=computed_at,
        )
    )
    db.commit()


def _call_mark_paid(client: TestClient, *, idem: str) -> tuple[int, dict[str, object]]:
    path = "/api/v1/bounties/bty_rev_gate_1/mark-paid"
    body = json.dumps({"paid_tx_hash": "0x" + "b" * 64}, separators=(",", ":"), sort_keys=True).encode("utf-8")
    response = client.post(path, content=body, headers=_oracle_headers(path, body, f"req-{idem}", idem=idem))
    return response.status_code, response.json()


def _assert_latest_audit(db: Session, *, idem: str, blocked_reason: str) -> None:
    audit = (
        db.query(AuditLog)
        .filter(AuditLog.path == "/api/v1/bounties/bty_rev_gate_1/mark-paid")
        .order_by(AuditLog.id.desc())
        .first()
    )
    assert audit is not None
    assert audit.idempotency_key == idem
    assert audit.error_hint is not None
    assert f"br={blocked_reason};" in audit.error_hint
    assert len(audit.error_hint) <= 255


def test_mark_paid_blocked_when_revenue_reconciliation_missing(
    _client: TestClient,
    _db: sessionmaker[Session],
) -> None:
    with _db() as db:
        _seed_project_bounty(db)

    status_code, data = _call_mark_paid(_client, idem="idem-rev-missing")
    assert status_code == 200
    assert data["success"] is False
    assert data["blocked_reason"] == "project_revenue_reconciliation_missing"

    with _db() as db:
        _assert_latest_audit(db, idem="idem-rev-missing", blocked_reason="project_revenue_reconciliation_missing")


def test_mark_paid_blocked_when_revenue_reconciliation_not_ready(
    _client: TestClient,
    _db: sessionmaker[Session],
) -> None:
    with _db() as db:
        bounty = _seed_project_bounty(db)
        _insert_reconciliation(
            db,
            project_id=bounty.project_id,
            ready=False,
            delta_micro_usdc=50,
            computed_at=datetime.now(timezone.utc),
        )

    status_code, data = _call_mark_paid(_client, idem="idem-rev-not-ready")
    assert status_code == 200
    assert data["success"] is False
    assert data["blocked_reason"] == "project_revenue_not_reconciled"

    with _db() as db:
        _assert_latest_audit(db, idem="idem-rev-not-ready", blocked_reason="project_revenue_not_reconciled")


def test_mark_paid_blocked_when_revenue_reconciliation_stale(
    _client: TestClient,
    _db: sessionmaker[Session],
) -> None:
    with _db() as db:
        bounty = _seed_project_bounty(db)
        _insert_reconciliation(
            db,
            project_id=bounty.project_id,
            ready=True,
            delta_micro_usdc=0,
            computed_at=datetime.now(timezone.utc) - timedelta(hours=2),
        )

    status_code, data = _call_mark_paid(_client, idem="idem-rev-stale")
    assert status_code == 200
    assert data["success"] is False
    assert data["blocked_reason"] == "project_revenue_reconciliation_stale"

    with _db() as db:
        _assert_latest_audit(db, idem="idem-rev-stale", blocked_reason="project_revenue_reconciliation_stale")


def test_mark_paid_fresh_revenue_reconciliation_reaches_insufficient_revenue_check(
    _client: TestClient,
    _db: sessionmaker[Session],
) -> None:
    with _db() as db:
        bounty = _seed_project_bounty(db)
        _insert_reconciliation(
            db,
            project_id=bounty.project_id,
            ready=True,
            delta_micro_usdc=0,
            computed_at=datetime.now(timezone.utc),
        )

    status_code, data = _call_mark_paid(_client, idem="idem-rev-insufficient")
    assert status_code == 200
    assert data["success"] is False
    assert data["blocked_reason"] == "insufficient_project_revenue"

    with _db() as db:
        _assert_latest_audit(db, idem="idem-rev-insufficient", blocked_reason="insufficient_project_revenue")

