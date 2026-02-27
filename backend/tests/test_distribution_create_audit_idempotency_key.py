from __future__ import annotations

import hashlib
import hmac
import sys
import time
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

# Make `src` importable whether pytest runs from repo root or backend/.
BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from src.api.v1.oracle_settlement import router as oracle_router
from src.api.v1 import oracle_settlement as oracle_mod
from src.core.config import get_settings
from src.core.database import Base, get_db
from src.core.security import build_oracle_hmac_v2_payload

# Ensure tables are registered on Base.metadata
from src.models.audit_log import AuditLog  # noqa: F401
from src.models.oracle_nonce import OracleNonce  # noqa: F401
from src.models.tx_outbox import TxOutbox  # noqa: F401
from src.models.reconciliation_report import ReconciliationReport  # noqa: F401
from src.services.blockchain import DistributionState


def _sign(secret: str, payload: str) -> str:
    return hmac.new(secret.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).hexdigest()


def _make_test_app(db_session_factory: sessionmaker[Session]) -> FastAPI:
    app = FastAPI()

    def _override_get_db():
        db = db_session_factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = _override_get_db
    app.include_router(oracle_router)
    return app


@pytest.fixture(autouse=True)
def _isolate_settings_cache() -> None:
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_distribution_create_blocked_not_ready_has_audit_idempotency_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    session_local = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    Base.metadata.create_all(bind=engine)

    secret = "test-secret"
    monkeypatch.setenv("ORACLE_HMAC_SECRET", secret)
    monkeypatch.setenv("ORACLE_REQUEST_TTL_SECONDS", "300")
    monkeypatch.setenv("ORACLE_CLOCK_SKEW_SECONDS", "5")
    monkeypatch.setenv("ORACLE_ACCEPT_LEGACY_SIGNATURES", "false")

    profit_month_id = "202602"
    profit_sum = 123

    # Insert a reconciliation report that is not ready (blocked path).
    with session_local() as db:
        report = ReconciliationReport(
            profit_month_id=profit_month_id,
            revenue_sum_micro_usdc=profit_sum,
            expense_sum_micro_usdc=0,
            profit_sum_micro_usdc=profit_sum,
            distributor_balance_micro_usdc=0,
            delta_micro_usdc=-profit_sum,
            ready=False,
            blocked_reason="balance_mismatch",
            rpc_chain_id=None,
            rpc_url_name=None,
        )
        db.add(report)
        db.commit()

    app = _make_test_app(session_local)
    client = TestClient(app)

    path = f"/api/v1/oracle/distributions/{profit_month_id}/create"
    body = b""
    body_hash = hashlib.sha256(body).hexdigest()
    timestamp = str(int(time.time()))
    request_id = "req-not-ready-1"

    payload = build_oracle_hmac_v2_payload(
        timestamp,
        request_id,
        "POST",
        path,
        body_hash,
    )
    signature = _sign(secret, payload)

    resp = client.post(
        path,
        content=body,
        headers={
            "X-Request-Timestamp": timestamp,
            "X-Request-Id": request_id,
            "X-Signature": signature,
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is False
    assert data["data"]["blocked_reason"] == "not_ready"
    assert data["data"]["idempotency_key"] == f"create_distribution:{profit_month_id}:{profit_sum}"

    with session_local() as db:
        audit = (
            db.query(AuditLog)
            .filter(AuditLog.actor_type == "oracle", AuditLog.path == path, AuditLog.request_id == request_id)
            .order_by(AuditLog.id.desc())
            .first()
        )
        assert audit is not None
        assert audit.idempotency_key == f"create_distribution:{profit_month_id}:{profit_sum}"


def test_distribution_create_returns_blocked_when_existing_task_is_safe_blocked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    session_local = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    Base.metadata.create_all(bind=engine)

    secret = "test-secret"
    monkeypatch.setenv("ORACLE_HMAC_SECRET", secret)
    monkeypatch.setenv("ORACLE_REQUEST_TTL_SECONDS", "300")
    monkeypatch.setenv("ORACLE_CLOCK_SKEW_SECONDS", "5")
    monkeypatch.setenv("ORACLE_ACCEPT_LEGACY_SIGNATURES", "false")
    monkeypatch.setenv("TX_OUTBOX_ENABLED", "true")

    profit_month_id = "202602"
    profit_sum = 123
    idem = f"create_distribution:{profit_month_id}:{profit_sum}"

    with session_local() as db:
        db.add(
            ReconciliationReport(
                profit_month_id=profit_month_id,
                revenue_sum_micro_usdc=profit_sum,
                expense_sum_micro_usdc=0,
                profit_sum_micro_usdc=profit_sum,
                distributor_balance_micro_usdc=profit_sum,
                delta_micro_usdc=0,
                ready=True,
                blocked_reason=None,
                rpc_chain_id=None,
                rpc_url_name=None,
            )
        )
        db.add(
            TxOutbox(
                task_id="txo_safe_blocked",
                idempotency_key=idem,
                task_type="create_distribution",
                payload_json='{"profit_month_id":"202602"}',
                tx_hash=None,
                result_json='{"stage":"safe_execution_required"}',
                status="blocked",
                attempts=1,
                last_error_hint="safe_execution_required",
                locked_at=None,
                locked_by=None,
            )
        )
        db.commit()

    monkeypatch.setattr(
        oracle_mod,
        "read_distribution_state",
        lambda _: DistributionState(exists=False, total_profit_micro_usdc=0, distributed=False),
    )

    app = _make_test_app(session_local)
    client = TestClient(app)

    path = f"/api/v1/oracle/distributions/{profit_month_id}/create"
    body = b""
    body_hash = hashlib.sha256(body).hexdigest()
    timestamp = str(int(time.time()))
    request_id = "req-safe-blocked-1"
    payload = build_oracle_hmac_v2_payload(timestamp, request_id, "POST", path, body_hash)
    signature = _sign(secret, payload)

    resp = client.post(
        path,
        content=body,
        headers={
            "X-Request-Timestamp": timestamp,
            "X-Request-Id": request_id,
            "X-Signature": signature,
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is False
    assert data["data"]["blocked_reason"] == "safe_execution_required"
    assert data["data"]["task_id"] == "txo_safe_blocked"
