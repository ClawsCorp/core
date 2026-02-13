from __future__ import annotations

import hashlib
import hmac
import json
import sys
import time
from pathlib import Path
from types import SimpleNamespace

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
from src.core.security import build_oracle_hmac_v2_payload, hash_api_key
from src.main import app

import src.models  # noqa: F401
from src.api.v1 import oracle_accounting, oracle_settlement
from src.models.agent import Agent
from src.models.audit_log import AuditLog
from src.models.reconciliation_report import ReconciliationReport
from src.models.revenue_event import RevenueEvent


ORACLE_SECRET = "test-oracle-secret"


def _sign(secret: str, payload: str) -> str:
    return hmac.new(secret.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).hexdigest()


def _oracle_headers(path: str, body: bytes, request_id: str) -> dict[str, str]:
    timestamp = str(int(time.time()))
    body_hash = hashlib.sha256(body).hexdigest()
    payload = build_oracle_hmac_v2_payload(timestamp, request_id, "POST", path, body_hash)
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


def test_revenue_event_duplicate_idempotency_key_no_500(_client: TestClient) -> None:
    path = "/api/v1/oracle/revenue-events"
    payload = {
        "profit_month_id": "202501",
        "project_id": None,
        "amount_micro_usdc": 123456,
        "tx_hash": None,
        "source": "oracle",
        "idempotency_key": "idem-revenue-1",
        "evidence_url": None,
    }
    body = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")

    first = _client.post(path, content=body, headers=_oracle_headers(path, body, "req-rev-1"))
    second = _client.post(path, content=body, headers=_oracle_headers(path, body, "req-rev-2"))

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["data"]["event_id"] == second.json()["data"]["event_id"]


def test_payout_sync_duplicate_idempotency_key_no_500(
    _client: TestClient,
    _db: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = "/api/v1/oracle/payouts/202501/sync"
    tx_hash = "0x" + "a" * 64

    with _db() as db:
        db.add(
            ReconciliationReport(
                profit_month_id="202501",
                revenue_sum_micro_usdc=100,
                expense_sum_micro_usdc=20,
                profit_sum_micro_usdc=80,
                distributor_balance_micro_usdc=80,
                delta_micro_usdc=0,
                ready=True,
                blocked_reason=None,
                rpc_chain_id=84532,
                rpc_url_name="base_sepolia",
            )
        )
        db.commit()

    monkeypatch.setattr(
        oracle_settlement,
        "read_distribution_state",
        lambda _: SimpleNamespace(exists=True, distributed=True),
    )

    body = json.dumps({"tx_hash": tx_hash}, separators=(",", ":"), sort_keys=True).encode("utf-8")
    first = _client.post(path, content=body, headers=_oracle_headers(path, body, "req-sync-1"))
    second = _client.post(path, content=body, headers=_oracle_headers(path, body, "req-sync-2"))

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["data"]["status"] == "synced"
    assert second.json()["data"]["status"] == "already_synced"


def test_discussion_post_duplicate_idempotency_key_no_500(
    _client: TestClient,
    _db: sessionmaker[Session],
) -> None:
    raw_api_key = "agent-alpha.secretkey"
    with _db() as db:
        db.add(
            Agent(
                agent_id="agent-alpha",
                name="Alpha",
                capabilities_json="{}",
                wallet_address=None,
                api_key_hash=hash_api_key(raw_api_key),
                api_key_last4=raw_api_key[-4:],
            )
        )
        db.commit()

    thread_path = "/api/v1/agent/discussions/threads"
    thread_resp = _client.post(
        thread_path,
        headers={"X-API-Key": raw_api_key},
        json={"scope": "global", "project_id": None, "title": "Race-safe thread"},
    )
    assert thread_resp.status_code == 200
    thread_id = thread_resp.json()["data"]["thread_id"]

    post_path = f"/api/v1/agent/discussions/threads/{thread_id}/posts"
    post_payload = {"body_md": "First body", "idempotency_key": "idem-discussion-post-1"}

    first = _client.post(post_path, headers={"X-API-Key": raw_api_key}, json=post_payload)
    second = _client.post(post_path, headers={"X-API-Key": raw_api_key}, json=post_payload)

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["data"]["post_id"] == second.json()["data"]["post_id"]


def test_atomic_audit_with_business_insert_rolls_back_together(
    _client: TestClient,
    _db: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = "/api/v1/oracle/revenue-events"
    payload = {
        "profit_month_id": "202501",
        "project_id": None,
        "amount_micro_usdc": 999,
        "tx_hash": None,
        "source": "oracle",
        "idempotency_key": "idem-atomic-1",
        "evidence_url": None,
    }
    body = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")

    original_record_audit = oracle_accounting.record_audit

    def _record_then_fail(*args, **kwargs):
        original_record_audit(*args, **kwargs)
        raise RuntimeError("forced audit failure")

    monkeypatch.setattr(oracle_accounting, "record_audit", _record_then_fail)

    response = _client.post(path, content=body, headers=_oracle_headers(path, body, "req-atomic-1"))
    assert response.status_code == 500

    with _db() as db:
        assert db.query(RevenueEvent).filter(RevenueEvent.idempotency_key == "idem-atomic-1").first() is None
        assert db.query(AuditLog).filter(AuditLog.idempotency_key == "idem-atomic-1").first() is None
