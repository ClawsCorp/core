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
from src.models.marketing_fee_accrual_event import MarketingFeeAccrualEvent
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
    monkeypatch.setenv("MARKETING_TREASURY_ADDRESS", "0x00000000000000000000000000000000000000aa")

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


def test_marketing_fee_deposit_enqueues_outbox_task(_client: TestClient, _db: sessionmaker[Session]) -> None:
    db = _db()
    try:
        db.add(
            MarketingFeeAccrualEvent(
                event_id="mfee_1",
                idempotency_key="mfee:seed:1",
                project_id=None,
                profit_month_id="202602",
                bucket="platform_revenue",
                source="seed",
                gross_amount_micro_usdc=4000,
                fee_amount_micro_usdc=40,
                chain_id=None,
                tx_hash=None,
                log_index=None,
                evidence_url=None,
            )
        )
        db.add(
            MarketingFeeAccrualEvent(
                event_id="mfee_2",
                idempotency_key="mfee:seed:2",
                project_id=None,
                profit_month_id="202602",
                bucket="project_capital",
                source="seed",
                gross_amount_micro_usdc=2200,
                fee_amount_micro_usdc=22,
                chain_id=None,
                tx_hash=None,
                log_index=None,
                evidence_url=None,
            )
        )
        db.commit()
    finally:
        db.close()

    path = "/api/v1/oracle/marketing/settlement/deposit"
    body = b"{}"
    resp = _client.post(path, content=body, headers=_oracle_headers(path, body, "req-m1", idem="idem-m1"))
    assert resp.status_code == 200
    payload = resp.json()["data"]
    assert payload["status"] == "submitted"
    assert payload["blocked_reason"] is None
    assert payload["amount_micro_usdc"] == 62
    assert payload["task_id"]

    db = _db()
    try:
        task = db.query(TxOutbox).filter(TxOutbox.task_id == payload["task_id"]).first()
        assert task is not None
        assert task.task_type == "deposit_marketing_fee"
        task_payload = json.loads(task.payload_json)
        assert int(task_payload["amount_micro_usdc"]) == 62
        assert str(task_payload["to_address"]).lower() == "0x00000000000000000000000000000000000000aa"
    finally:
        db.close()


def test_marketing_fee_deposit_blocks_when_already_funded(_client: TestClient, _db: sessionmaker[Session]) -> None:
    db = _db()
    try:
        db.add(
            MarketingFeeAccrualEvent(
                event_id="mfee_3",
                idempotency_key="mfee:seed:3",
                project_id=None,
                profit_month_id="202602",
                bucket="platform_revenue",
                source="seed",
                gross_amount_micro_usdc=5000,
                fee_amount_micro_usdc=50,
                chain_id=None,
                tx_hash=None,
                log_index=None,
                evidence_url=None,
            )
        )
        db.add(
            TxOutbox(
                task_id="txo_seed_success",
                idempotency_key="deposit_marketing_fee:50:0",
                task_type="deposit_marketing_fee",
                payload_json=json.dumps({"amount_micro_usdc": 50, "to_address": "0x00000000000000000000000000000000000000aa"}),
                tx_hash="0x" + "1" * 64,
                result_json=None,
                status="succeeded",
                attempts=1,
                last_error_hint=None,
                locked_at=None,
                locked_by=None,
            )
        )
        db.commit()
    finally:
        db.close()

    path = "/api/v1/oracle/marketing/settlement/deposit"
    body = b"{}"
    resp = _client.post(path, content=body, headers=_oracle_headers(path, body, "req-m2", idem="idem-m2"))
    assert resp.status_code == 200
    payload = resp.json()["data"]
    assert payload["status"] == "blocked"
    assert payload["blocked_reason"] == "already_funded"
    assert payload["amount_micro_usdc"] == 0


def test_marketing_fee_deposit_counts_inflight_tasks_and_enqueues_only_delta(
    _client: TestClient, _db: sessionmaker[Session]
) -> None:
    db = _db()
    try:
        db.add(
            MarketingFeeAccrualEvent(
                event_id="mfee_4",
                idempotency_key="mfee:seed:4",
                project_id=None,
                profit_month_id="202602",
                bucket="platform_revenue",
                source="seed",
                gross_amount_micro_usdc=10000,
                fee_amount_micro_usdc=100,
                chain_id=None,
                tx_hash=None,
                log_index=None,
                evidence_url=None,
            )
        )
        # Earlier in-flight transfer for 60 micro-USDC should be treated as already committed.
        db.add(
            TxOutbox(
                task_id="txo_seed_pending",
                idempotency_key="deposit_marketing_fee:60:0",
                task_type="deposit_marketing_fee",
                payload_json=json.dumps({"amount_micro_usdc": 60, "to_address": "0x00000000000000000000000000000000000000aa"}),
                tx_hash=None,
                result_json=None,
                status="pending",
                attempts=0,
                last_error_hint=None,
                locked_at=None,
                locked_by=None,
            )
        )
        db.commit()
    finally:
        db.close()

    path = "/api/v1/oracle/marketing/settlement/deposit"
    body = b"{}"
    resp = _client.post(path, content=body, headers=_oracle_headers(path, body, "req-m3", idem="idem-m3"))
    assert resp.status_code == 200
    payload = resp.json()["data"]
    assert payload["status"] == "submitted"
    assert payload["blocked_reason"] is None
    assert payload["amount_micro_usdc"] == 40
    assert payload["accrued_total_micro_usdc"] == 100
    assert payload["sent_total_micro_usdc"] == 60

    db = _db()
    try:
        pending_rows = (
            db.query(TxOutbox)
            .filter(TxOutbox.task_type == "deposit_marketing_fee", TxOutbox.status == "pending")
            .order_by(TxOutbox.id.asc())
            .all()
        )
        assert len(pending_rows) == 2
        amounts = [int(json.loads(r.payload_json).get("amount_micro_usdc") or 0) for r in pending_rows]
        assert amounts == [60, 40]
    finally:
        db.close()
