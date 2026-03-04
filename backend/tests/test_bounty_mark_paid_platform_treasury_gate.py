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
from src.models.expense_event import ExpenseEvent
from src.models.platform_capital_event import PlatformCapitalEvent
from src.models.platform_capital_reconciliation_report import PlatformCapitalReconciliationReport

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
    monkeypatch.setenv("PLATFORM_CAPITAL_RECONCILIATION_MAX_AGE_SECONDS", "3600")

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


def _seed_platform_bounty(db: Session) -> Bounty:
    bounty = Bounty(
        bounty_id="bty_platform_gate_1",
        project_id=None,
        funding_source=BountyFundingSource.platform_treasury,
        title="Platform hardening",
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
    ready: bool,
    delta_micro_usdc: int | None,
    computed_at: datetime,
) -> None:
    db.add(
        PlatformCapitalReconciliationReport(
            funding_pool_address="0x" + "1" * 40,
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
    path = "/api/v1/bounties/bty_platform_gate_1/mark-paid"
    body = json.dumps({"paid_tx_hash": "0x" + "b" * 64}, separators=(",", ":"), sort_keys=True).encode("utf-8")
    response = client.post(path, content=body, headers=_oracle_headers(path, body, f"req-{idem}", idem=idem))
    return response.status_code, response.json()


def _assert_latest_audit(db: Session, *, idem: str, blocked_reason: str) -> None:
    audit = (
        db.query(AuditLog)
        .filter(AuditLog.path == "/api/v1/bounties/bty_platform_gate_1/mark-paid")
        .order_by(AuditLog.id.desc())
        .first()
    )
    assert audit is not None
    assert audit.idempotency_key == idem
    assert audit.error_hint is not None
    assert f"br={blocked_reason};" in audit.error_hint


def test_mark_paid_blocked_when_platform_reconciliation_missing(
    _client: TestClient,
    _db: sessionmaker[Session],
) -> None:
    with _db() as db:
        _seed_platform_bounty(db)

    status_code, data = _call_mark_paid(_client, idem="idem-platform-missing")
    assert status_code == 200
    assert data["success"] is False
    assert data["blocked_reason"] == "platform_capital_reconciliation_missing"

    with _db() as db:
        assert db.query(ExpenseEvent).count() == 0
        assert db.query(PlatformCapitalEvent).count() == 0
        _assert_latest_audit(
            db,
            idem="idem-platform-missing",
            blocked_reason="platform_capital_reconciliation_missing",
        )


def test_mark_paid_blocked_when_platform_reconciliation_stale(
    _client: TestClient,
    _db: sessionmaker[Session],
) -> None:
    with _db() as db:
        _seed_platform_bounty(db)
        _insert_reconciliation(
            db,
            ready=True,
            delta_micro_usdc=0,
            computed_at=datetime.now(timezone.utc) - timedelta(hours=2),
        )

    status_code, data = _call_mark_paid(_client, idem="idem-platform-stale")
    assert status_code == 200
    assert data["success"] is False
    assert data["blocked_reason"] == "platform_capital_reconciliation_stale"


def test_mark_paid_fresh_platform_reconciliation_reaches_insufficient_capital_check(
    _client: TestClient,
    _db: sessionmaker[Session],
) -> None:
    with _db() as db:
        _seed_platform_bounty(db)
        _insert_reconciliation(
            db,
            ready=True,
            delta_micro_usdc=0,
            computed_at=datetime.now(timezone.utc),
        )

    status_code, data = _call_mark_paid(_client, idem="idem-platform-insufficient")
    assert status_code == 200
    assert data["success"] is False
    assert data["blocked_reason"] == "insufficient_platform_capital"


def test_mark_paid_platform_treasury_creates_append_only_outflow(
    _client: TestClient,
    _db: sessionmaker[Session],
) -> None:
    with _db() as db:
        bounty = _seed_platform_bounty(db)
        db.add(
            PlatformCapitalEvent(
                event_id="platcap_seed_1",
                idempotency_key="platcap:seed:1",
                profit_month_id=datetime.now(timezone.utc).strftime("%Y%m"),
                delta_micro_usdc=2_000_000,
                source="seed_funding",
                evidence_tx_hash="0x" + "c" * 64,
                evidence_url="seed",
            )
        )
        _insert_reconciliation(
            db,
            ready=True,
            delta_micro_usdc=0,
            computed_at=datetime.now(timezone.utc),
        )
        db.commit()
        assert bounty.status == BountyStatus.eligible_for_payout

    status_code, data = _call_mark_paid(_client, idem="idem-platform-paid")
    assert status_code == 200
    assert data["success"] is True
    assert data["blocked_reason"] is None

    with _db() as db:
        bounty = db.query(Bounty).filter(Bounty.bounty_id == "bty_platform_gate_1").first()
        assert bounty is not None
        assert bounty.status == BountyStatus.paid
        assert db.query(ExpenseEvent).count() == 1
        events = db.query(PlatformCapitalEvent).order_by(PlatformCapitalEvent.id.asc()).all()
        assert len(events) == 2
        assert int(events[1].delta_micro_usdc) == -1_000_000
        assert events[1].idempotency_key == "platcap:bounty_paid:bty_platform_gate_1"
