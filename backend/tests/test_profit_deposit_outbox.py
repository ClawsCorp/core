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
from src.models.reconciliation_report import ReconciliationReport
from src.models.tx_outbox import TxOutbox

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
    monkeypatch.setenv("TX_OUTBOX_ENABLED", "true")

    # Required to pass config validation for deposit endpoint.
    monkeypatch.setenv("DIVIDEND_DISTRIBUTOR_CONTRACT_ADDRESS", "0x000000000000000000000000000000000000dEaD")

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


def test_profit_deposit_enqueues_outbox_task_when_balance_low(_client: TestClient, _db: sessionmaker[Session]) -> None:
    profit_month_id = "202602"

    # Insert a reconciliation report where distributor balance is below profit (delta negative).
    # delta = balance - profit
    body = b"{}"

    db = _db()
    try:
        # NOTE: keep values simple; only delta/profit_sum are used.
        db.add(
            ReconciliationReport(
                profit_month_id=profit_month_id,
                revenue_sum_micro_usdc=2000,
                expense_sum_micro_usdc=0,
                profit_sum_micro_usdc=2000,
                distributor_balance_micro_usdc=1500,
                delta_micro_usdc=-500,
                ready=False,
                blocked_reason="balance_mismatch",
                rpc_chain_id=84532,
                rpc_url_name="base_sepolia",
            )
        )
        db.commit()
    finally:
        db.close()

    path = f"/api/v1/oracle/settlement/{profit_month_id}/deposit-profit"
    resp = _client.post(
        path,
        content=body,
        headers=_oracle_headers(path, body, "req-1", idem="idem-1"),
    )
    assert resp.status_code == 200
    payload = resp.json()["data"]
    assert payload["status"] == "submitted"
    assert payload["blocked_reason"] is None
    assert payload["task_id"]
    assert payload["amount_micro_usdc"] == 500

    # Ensure task exists and is idempotent.
    task_id = payload["task_id"]
    db = _db()
    try:
        task = db.query(TxOutbox).filter(TxOutbox.task_id == task_id).first()
        assert task is not None
        assert task.task_type == "deposit_profit"
        assert json.loads(task.payload_json)["amount_micro_usdc"] == 500
        assert task.status == "pending"
    finally:
        db.close()

    resp2 = _client.post(
        path,
        content=body,
        headers=_oracle_headers(path, body, "req-2", idem="idem-2"),
    )
    assert resp2.status_code == 200
    payload2 = resp2.json()["data"]
    assert payload2["task_id"] == task_id


def test_profit_deposit_blocks_on_balance_excess(_client: TestClient, _db: sessionmaker[Session]) -> None:
    profit_month_id = "202602"
    body = b"{}"

    db = _db()
    try:
        db.add(
            ReconciliationReport(
                profit_month_id=profit_month_id,
                revenue_sum_micro_usdc=1000,
                expense_sum_micro_usdc=0,
                profit_sum_micro_usdc=1000,
                distributor_balance_micro_usdc=1500,
                delta_micro_usdc=500,
                ready=False,
                blocked_reason="balance_mismatch",
                rpc_chain_id=84532,
                rpc_url_name="base_sepolia",
            )
        )
        db.commit()
    finally:
        db.close()

    path = f"/api/v1/oracle/settlement/{profit_month_id}/deposit-profit"
    resp = _client.post(
        path,
        content=body,
        headers=_oracle_headers(path, body, "req-3", idem="idem-3"),
    )
    assert resp.status_code == 200
    payload = resp.json()["data"]
    assert payload["status"] == "blocked"
    assert payload["blocked_reason"] == "balance_excess"
