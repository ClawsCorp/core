from __future__ import annotations

import hashlib
import hmac
import json
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

from src.api.v1 import oracle_settlement as oracle_mod
from src.api.v1.oracle_settlement import router as oracle_router
from src.core.config import get_settings
from src.core.database import Base, get_db
from src.core.security import build_oracle_hmac_v2_payload
from src.models.audit_log import AuditLog
from src.models.distribution_execution import DistributionExecution  # noqa: F401
from src.models.oracle_nonce import OracleNonce  # noqa: F401
from src.models.reconciliation_report import ReconciliationReport
from src.models.settlement import Settlement
from src.services.blockchain import BlockchainConfigError, BlockchainTxError, DistributionState


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


def _post_signed(
    client: TestClient,
    *,
    secret: str,
    request_id: str,
    path: str,
    body: bytes,
) -> tuple[int, dict]:
    body_hash = hashlib.sha256(body).hexdigest()
    timestamp = str(int(time.time()))
    payload = build_oracle_hmac_v2_payload(timestamp, request_id, "POST", path, body_hash)
    signature = _sign(secret, payload)

    resp = client.post(
        path,
        content=body,
        headers={
            "X-Request-Timestamp": timestamp,
            "X-Request-Id": request_id,
            "X-Signature": signature,
            "Content-Type": "application/json",
        },
    )
    return resp.status_code, resp.json()


def _insert_settlement(db: Session, *, profit_month_id: str, profit_sum: int) -> None:
    settlement = Settlement(
        profit_month_id=profit_month_id,
        revenue_sum_micro_usdc=profit_sum,
        expense_sum_micro_usdc=0,
        profit_sum_micro_usdc=profit_sum,
        profit_nonnegative=profit_sum >= 0,
    )
    db.add(settlement)
    db.commit()


def _insert_reconciliation(
    db: Session,
    *,
    profit_month_id: str,
    profit_sum: int,
    ready: bool,
    delta_micro_usdc: int | None,
) -> None:
    report = ReconciliationReport(
        profit_month_id=profit_month_id,
        revenue_sum_micro_usdc=profit_sum,
        expense_sum_micro_usdc=0,
        profit_sum_micro_usdc=profit_sum,
        distributor_balance_micro_usdc=profit_sum + (delta_micro_usdc or 0),
        delta_micro_usdc=delta_micro_usdc,
        ready=ready,
        blocked_reason=None if ready and (delta_micro_usdc or 0) == 0 else "balance_mismatch",
        rpc_chain_id=None,
        rpc_url_name=None,
    )
    db.add(report)
    db.commit()


def _assert_audit_has_idempotency_key(
    session_local: sessionmaker[Session],
    *,
    request_id: str,
    path: str,
    expected_idempotency_key: str,
) -> None:
    with session_local() as db:
        audit = (
            db.query(AuditLog)
            .filter(AuditLog.actor_type == "oracle", AuditLog.path == path, AuditLog.request_id == request_id)
            .order_by(AuditLog.id.desc())
            .first()
        )
        assert audit is not None
        assert audit.idempotency_key == expected_idempotency_key


def test_distribution_execute_blocked_reconciliation_missing_has_audit_idempotency_key(
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
    profit_sum = 20_000_000
    with session_local() as db:
        _insert_settlement(db, profit_month_id=profit_month_id, profit_sum=profit_sum)

    app = _make_test_app(session_local)
    client = TestClient(app)

    path = f"/api/v1/oracle/distributions/{profit_month_id}/execute"
    payload = {
        "stakers": ["0xf965d65a9E0197B6900ba350964fBC545ec490ed"],
        "staker_shares": [1],
        "authors": ["0xd061ccf208B8382B800dB8534a638705079A693e"],
        "author_shares": [1],
    }
    body = json.dumps(payload, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    request_id = "req-exec-recon-missing-1"

    status, data = _post_signed(client, secret=secret, request_id=request_id, path=path, body=body)
    assert status == 200
    assert data["success"] is False
    assert data["data"]["blocked_reason"] == "reconciliation_missing"
    assert data["data"]["idempotency_key"]

    _assert_audit_has_idempotency_key(
        session_local,
        request_id=request_id,
        path=path,
        expected_idempotency_key=data["data"]["idempotency_key"],
    )


def test_distribution_execute_blocked_not_ready_has_audit_idempotency_key(
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
    profit_sum = 20_000_000
    with session_local() as db:
        _insert_settlement(db, profit_month_id=profit_month_id, profit_sum=profit_sum)
        _insert_reconciliation(
            db,
            profit_month_id=profit_month_id,
            profit_sum=profit_sum,
            ready=False,
            delta_micro_usdc=-1,
        )

    app = _make_test_app(session_local)
    client = TestClient(app)

    path = f"/api/v1/oracle/distributions/{profit_month_id}/execute"
    payload = {
        "stakers": ["0xf965d65a9E0197B6900ba350964fBC545ec490ed"],
        "staker_shares": [1],
        "authors": ["0xd061ccf208B8382B800dB8534a638705079A693e"],
        "author_shares": [1],
    }
    body = json.dumps(payload, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    request_id = "req-exec-not-ready-1"

    status, data = _post_signed(client, secret=secret, request_id=request_id, path=path, body=body)
    assert status == 200
    assert data["success"] is False
    assert data["data"]["blocked_reason"] == "not_ready"
    assert data["data"]["idempotency_key"]

    _assert_audit_has_idempotency_key(
        session_local,
        request_id=request_id,
        path=path,
        expected_idempotency_key=data["data"]["idempotency_key"],
    )


def test_distribution_execute_blocked_rpc_not_configured_has_audit_idempotency_key(
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
    profit_sum = 20_000_000
    with session_local() as db:
        _insert_settlement(db, profit_month_id=profit_month_id, profit_sum=profit_sum)
        _insert_reconciliation(
            db,
            profit_month_id=profit_month_id,
            profit_sum=profit_sum,
            ready=True,
            delta_micro_usdc=0,
        )

    def _raise_config(_: int) -> DistributionState:
        raise BlockchainConfigError("Missing BASE_SEPOLIA_RPC_URL, USDC_ADDRESS, or DIVIDEND_DISTRIBUTOR_CONTRACT_ADDRESS")

    monkeypatch.setattr(oracle_mod, "read_distribution_state", _raise_config)

    app = _make_test_app(session_local)
    client = TestClient(app)

    path = f"/api/v1/oracle/distributions/{profit_month_id}/execute"
    payload = {
        "stakers": ["0xf965d65a9E0197B6900ba350964fBC545ec490ed"],
        "staker_shares": [1],
        "authors": ["0xd061ccf208B8382B800dB8534a638705079A693e"],
        "author_shares": [1],
    }
    body = json.dumps(payload, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    request_id = "req-exec-rpc-not-configured-1"

    status, data = _post_signed(client, secret=secret, request_id=request_id, path=path, body=body)
    assert status == 200
    assert data["success"] is False
    assert data["data"]["blocked_reason"] == "rpc_not_configured"
    assert data["data"]["idempotency_key"]

    _assert_audit_has_idempotency_key(
        session_local,
        request_id=request_id,
        path=path,
        expected_idempotency_key=data["data"]["idempotency_key"],
    )


def test_distribution_execute_blocked_signer_key_required_has_audit_idempotency_key(
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
    profit_sum = 20_000_000
    with session_local() as db:
        _insert_settlement(db, profit_month_id=profit_month_id, profit_sum=profit_sum)
        _insert_reconciliation(
            db,
            profit_month_id=profit_month_id,
            profit_sum=profit_sum,
            ready=True,
            delta_micro_usdc=0,
        )

    monkeypatch.setattr(
        oracle_mod,
        "read_distribution_state",
        lambda _: DistributionState(exists=True, total_profit_micro_usdc=profit_sum, distributed=False),
    )

    def _raise_signer_missing(**_: object) -> str:
        raise BlockchainConfigError("Missing ORACLE_SIGNER_PRIVATE_KEY")

    monkeypatch.setattr(oracle_mod, "submit_execute_distribution_tx", _raise_signer_missing)

    app = _make_test_app(session_local)
    client = TestClient(app)

    path = f"/api/v1/oracle/distributions/{profit_month_id}/execute"
    payload = {
        "stakers": ["0xf965d65a9E0197B6900ba350964fBC545ec490ed"],
        "staker_shares": [1],
        "authors": ["0xd061ccf208B8382B800dB8534a638705079A693e"],
        "author_shares": [1],
    }
    body = json.dumps(payload, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    request_id = "req-exec-signer-required-1"

    status, data = _post_signed(client, secret=secret, request_id=request_id, path=path, body=body)
    assert status == 200
    assert data["success"] is False
    assert data["data"]["blocked_reason"] == "signer_key_required"
    assert data["data"]["idempotency_key"]

    _assert_audit_has_idempotency_key(
        session_local,
        request_id=request_id,
        path=path,
        expected_idempotency_key=data["data"]["idempotency_key"],
    )


def test_distribution_execute_blocked_tx_error_has_audit_idempotency_key_and_error_hint(
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
    profit_sum = 20_000_000
    with session_local() as db:
        _insert_settlement(db, profit_month_id=profit_month_id, profit_sum=profit_sum)
        _insert_reconciliation(
            db,
            profit_month_id=profit_month_id,
            profit_sum=profit_sum,
            ready=True,
            delta_micro_usdc=0,
        )

    monkeypatch.setattr(
        oracle_mod,
        "read_distribution_state",
        lambda _: DistributionState(exists=True, total_profit_micro_usdc=profit_sum, distributed=False),
    )

    def _raise_tx(**_: object) -> str:
        raise BlockchainTxError("failed", error_hint="boom")

    monkeypatch.setattr(oracle_mod, "submit_execute_distribution_tx", _raise_tx)

    app = _make_test_app(session_local)
    client = TestClient(app)

    path = f"/api/v1/oracle/distributions/{profit_month_id}/execute"
    payload = {
        "stakers": ["0xf965d65a9E0197B6900ba350964fBC545ec490ed"],
        "staker_shares": [1],
        "authors": ["0xd061ccf208B8382B800dB8534a638705079A693e"],
        "author_shares": [1],
    }
    body = json.dumps(payload, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    request_id = "req-exec-tx-error-1"

    status, data = _post_signed(client, secret=secret, request_id=request_id, path=path, body=body)
    assert status == 200
    assert data["success"] is False
    assert data["data"]["blocked_reason"] == "tx_error"
    assert data["data"]["idempotency_key"]

    _assert_audit_has_idempotency_key(
        session_local,
        request_id=request_id,
        path=path,
        expected_idempotency_key=data["data"]["idempotency_key"],
    )

    with session_local() as db:
        audit = (
            db.query(AuditLog)
            .filter(AuditLog.actor_type == "oracle", AuditLog.path == path, AuditLog.request_id == request_id)
            .order_by(AuditLog.id.desc())
            .first()
        )
        assert audit is not None
        # Avoid brittle expectations: the hint may be decorated/sanitized in some environments.
        assert audit.error_hint is not None
        assert "boom" in audit.error_hint


def test_distribution_execute_blocked_validation_failure_has_audit_idempotency_key(
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
    profit_sum = 20_000_000
    with session_local() as db:
        _insert_settlement(db, profit_month_id=profit_month_id, profit_sum=profit_sum)
        _insert_reconciliation(
            db,
            profit_month_id=profit_month_id,
            profit_sum=profit_sum,
            ready=True,
            delta_micro_usdc=0,
        )

    monkeypatch.setattr(
        oracle_mod,
        "read_distribution_state",
        lambda _: DistributionState(exists=True, total_profit_micro_usdc=profit_sum, distributed=False),
    )

    app = _make_test_app(session_local)
    client = TestClient(app)

    path = f"/api/v1/oracle/distributions/{profit_month_id}/execute"
    payload = {
        "stakers": ["0xf965d65a9E0197B6900ba350964fBC545ec490ed"],
        # Length mismatch triggers a blocked validation path.
        "staker_shares": [1, 2],
        "authors": ["0xd061ccf208B8382B800dB8534a638705079A693e"],
        "author_shares": [1],
    }
    body = json.dumps(payload, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    request_id = "req-exec-validation-1"

    status, data = _post_signed(client, secret=secret, request_id=request_id, path=path, body=body)
    assert status == 200
    assert data["success"] is False
    assert data["data"]["blocked_reason"] == "recipient_shares_length_mismatch"
    assert data["data"]["idempotency_key"]

    _assert_audit_has_idempotency_key(
        session_local,
        request_id=request_id,
        path=path,
        expected_idempotency_key=data["data"]["idempotency_key"],
    )


def test_distribution_execute_blocked_when_no_recipients_has_audit_idempotency_key(
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
    profit_sum = 20_000_000
    with session_local() as db:
        _insert_settlement(db, profit_month_id=profit_month_id, profit_sum=profit_sum)
        _insert_reconciliation(
            db,
            profit_month_id=profit_month_id,
            profit_sum=profit_sum,
            ready=True,
            delta_micro_usdc=0,
        )

    monkeypatch.setattr(
        oracle_mod,
        "read_distribution_state",
        lambda _: DistributionState(exists=True, total_profit_micro_usdc=profit_sum, distributed=False),
    )

    app = _make_test_app(session_local)
    client = TestClient(app)

    path = f"/api/v1/oracle/distributions/{profit_month_id}/execute"
    payload = {
        "stakers": [],
        "staker_shares": [],
        "authors": [],
        "author_shares": [],
    }
    body = json.dumps(payload, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    request_id = "req-exec-no-recipients-1"

    status, data = _post_signed(client, secret=secret, request_id=request_id, path=path, body=body)
    assert status == 200
    assert data["success"] is False
    assert data["data"]["blocked_reason"] == "recipients_required"
    assert data["data"]["idempotency_key"]

    _assert_audit_has_idempotency_key(
        session_local,
        request_id=request_id,
        path=path,
        expected_idempotency_key=data["data"]["idempotency_key"],
    )


def test_distribution_execute_blocked_distribution_missing_has_audit_idempotency_key(
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
    profit_sum = 20_000_000
    with session_local() as db:
        _insert_settlement(db, profit_month_id=profit_month_id, profit_sum=profit_sum)
        _insert_reconciliation(
            db,
            profit_month_id=profit_month_id,
            profit_sum=profit_sum,
            ready=True,
            delta_micro_usdc=0,
        )

    monkeypatch.setattr(
        oracle_mod,
        "read_distribution_state",
        lambda _: DistributionState(exists=False, total_profit_micro_usdc=0, distributed=False),
    )

    app = _make_test_app(session_local)
    client = TestClient(app)

    path = f"/api/v1/oracle/distributions/{profit_month_id}/execute"
    payload = {
        "stakers": ["0xf965d65a9E0197B6900ba350964fBC545ec490ed"],
        "staker_shares": [1],
        "authors": ["0xd061ccf208B8382B800dB8534a638705079A693e"],
        "author_shares": [1],
    }
    body = json.dumps(payload, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    request_id = "req-exec-dist-missing-1"

    status, data = _post_signed(client, secret=secret, request_id=request_id, path=path, body=body)
    assert status == 200
    assert data["success"] is False
    assert data["data"]["blocked_reason"] == "distribution_missing"
    assert data["data"]["idempotency_key"]

    _assert_audit_has_idempotency_key(
        session_local,
        request_id=request_id,
        path=path,
        expected_idempotency_key=data["data"]["idempotency_key"],
    )


def test_distribution_execute_already_distributed_has_audit_idempotency_key(
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
    profit_sum = 20_000_000
    with session_local() as db:
        _insert_settlement(db, profit_month_id=profit_month_id, profit_sum=profit_sum)
        _insert_reconciliation(
            db,
            profit_month_id=profit_month_id,
            profit_sum=profit_sum,
            ready=True,
            delta_micro_usdc=0,
        )

    monkeypatch.setattr(
        oracle_mod,
        "read_distribution_state",
        lambda _: DistributionState(exists=True, total_profit_micro_usdc=profit_sum, distributed=True),
    )

    app = _make_test_app(session_local)
    client = TestClient(app)

    path = f"/api/v1/oracle/distributions/{profit_month_id}/execute"
    payload = {
        "stakers": ["0xf965d65a9E0197B6900ba350964fBC545ec490ed"],
        "staker_shares": [1],
        "authors": ["0xd061ccf208B8382B800dB8534a638705079A693e"],
        "author_shares": [1],
    }
    body = json.dumps(payload, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    request_id = "req-exec-already-distributed-1"

    status, data = _post_signed(client, secret=secret, request_id=request_id, path=path, body=body)
    assert status == 200
    assert data["success"] is True
    assert data["data"]["status"] == "already_distributed"
    assert data["data"]["blocked_reason"] is None
    assert data["data"]["idempotency_key"]

    _assert_audit_has_idempotency_key(
        session_local,
        request_id=request_id,
        path=path,
        expected_idempotency_key=data["data"]["idempotency_key"],
    )


def test_distribution_execute_blocked_total_profit_mismatch_has_audit_idempotency_key(
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
    profit_sum = 20_000_000
    with session_local() as db:
        _insert_settlement(db, profit_month_id=profit_month_id, profit_sum=profit_sum)
        _insert_reconciliation(
            db,
            profit_month_id=profit_month_id,
            profit_sum=profit_sum,
            ready=True,
            delta_micro_usdc=0,
        )

    monkeypatch.setattr(
        oracle_mod,
        "read_distribution_state",
        lambda _: DistributionState(exists=True, total_profit_micro_usdc=profit_sum + 1, distributed=False),
    )

    app = _make_test_app(session_local)
    client = TestClient(app)

    path = f"/api/v1/oracle/distributions/{profit_month_id}/execute"
    payload = {
        "stakers": ["0xf965d65a9E0197B6900ba350964fBC545ec490ed"],
        "staker_shares": [1],
        "authors": ["0xd061ccf208B8382B800dB8534a638705079A693e"],
        "author_shares": [1],
    }
    body = json.dumps(payload, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    request_id = "req-exec-profit-mismatch-1"

    status, data = _post_signed(client, secret=secret, request_id=request_id, path=path, body=body)
    assert status == 200
    assert data["success"] is False
    assert data["data"]["blocked_reason"] == "distribution_total_mismatch"
    assert data["data"]["idempotency_key"]

    _assert_audit_has_idempotency_key(
        session_local,
        request_id=request_id,
        path=path,
        expected_idempotency_key=data["data"]["idempotency_key"],
    )
