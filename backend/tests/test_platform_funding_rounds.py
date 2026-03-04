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
from src.models.agent import Agent
from src.models.observed_usdc_transfer import ObservedUsdcTransfer
from src.models.platform_capital_event import PlatformCapitalEvent
from src.models.reputation_event import ReputationEvent

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


def test_platform_funding_open_blocks_when_pool_missing(_client: TestClient) -> None:
    path = "/api/v1/oracle/platform/funding-rounds"
    body = json.dumps({"idempotency_key": "pfr-open-1", "title": "Platform Round 1", "cap_micro_usdc": 1_000_000}).encode(
        "utf-8"
    )
    resp = _client.post(path, content=body, headers=_oracle_headers(path, body, "req-pfr-missing", idem="idem-pfr-missing"))
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["success"] is False
    assert payload["blocked_reason"] == "funding_pool_address_missing"


def test_platform_funding_sync_and_summary(_client: TestClient, _db: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch) -> None:
    pool = "0x9999999999999999999999999999999999999999"
    from_addr = "0x1111111111111111111111111111111111111111"
    monkeypatch.setenv("FUNDING_POOL_CONTRACT_ADDRESS", pool)
    get_settings.cache_clear()

    with _db() as db:
        db.add(
            Agent(
                agent_id="ag_platform_round_investor",
                name="Platform Round Investor",
                capabilities_json="[]",
                wallet_address=from_addr,
                api_key_hash="hash",
                api_key_last4="1111",
            )
        )
        db.commit()

    path_open = "/api/v1/oracle/platform/funding-rounds"
    body_open = json.dumps({"idempotency_key": "pfr-open-2", "title": "Platform Genesis", "cap_micro_usdc": 5_000}).encode(
        "utf-8"
    )
    resp_open = _client.post(path_open, content=body_open, headers=_oracle_headers(path_open, body_open, "req-pfr-open", idem="idem-pfr-open"))
    assert resp_open.status_code == 200
    payload_open = resp_open.json()
    assert payload_open["success"] is True
    round_id = payload_open["data"]["round_id"]

    with _db() as db:
        db.add(
            ObservedUsdcTransfer(
                chain_id=84532,
                token_address="0x0000000000000000000000000000000000000bbb",
                from_address=from_addr,
                to_address=pool,
                amount_micro_usdc=1234,
                block_number=10,
                tx_hash="0x" + ("22" * 32),
                log_index=1,
            )
        )
        db.commit()

    path_sync = "/api/v1/oracle/platform-funding/sync"
    body_sync = b"{}"
    resp_sync = _client.post(path_sync, content=body_sync, headers=_oracle_headers(path_sync, body_sync, "req-pfr-sync", idem="idem-pfr-sync"))
    assert resp_sync.status_code == 200
    payload_sync = resp_sync.json()
    assert payload_sync["success"] is True
    assert payload_sync["data"]["deposits_inserted"] == 1
    assert payload_sync["data"]["reputation_events_created"] == 1
    assert payload_sync["data"]["recognized_investor_transfers"] == 1
    assert payload_sync["data"]["open_round_id"] == round_id

    with _db() as db:
        rep_rows = db.query(ReputationEvent).all()
        assert len(rep_rows) == 1
        assert rep_rows[0].source == "platform_capital_contributed"

    resp_summary = _client.get("/api/v1/platform/funding")
    assert resp_summary.status_code == 200
    summary = resp_summary.json()["data"]
    assert summary["open_round"]["round_id"] == round_id
    assert summary["open_round_raised_micro_usdc"] == 1234
    assert summary["total_raised_micro_usdc"] == 1234
    assert summary["contributors_total_count"] == 1
    assert summary["contributors"][0]["address"] == from_addr
    assert summary["contributors"][0]["amount_micro_usdc"] == 1234
    assert summary["contributors_data_source"] == "observed_transfers"
    assert summary["blocked_reason"] is None

    path_close = f"/api/v1/oracle/platform/funding-rounds/{round_id}/close"
    body_close = json.dumps({"idempotency_key": "pfr-close-2"}).encode("utf-8")
    resp_close = _client.post(path_close, content=body_close, headers=_oracle_headers(path_close, body_close, "req-pfr-close", idem="idem-pfr-close"))
    assert resp_close.status_code == 200
    assert resp_close.json()["success"] is True
    assert resp_close.json()["data"]["status"] == "closed"


def test_platform_funding_summary_uses_ledger_fallback_when_indexer_lags(
    _client: TestClient, _db: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch
) -> None:
    pool = "0x9999999999999999999999999999999999999999"
    monkeypatch.setenv("FUNDING_POOL_CONTRACT_ADDRESS", pool)
    get_settings.cache_clear()

    path_open = "/api/v1/oracle/platform/funding-rounds"
    body_open = json.dumps({"idempotency_key": "pfr-open-fallback", "title": "Fallback Round", "cap_micro_usdc": 9_999}).encode(
        "utf-8"
    )
    resp_open = _client.post(
        path_open,
        content=body_open,
        headers=_oracle_headers(path_open, body_open, "req-pfr-open-fallback", idem="idem-pfr-open-fallback"),
    )
    assert resp_open.status_code == 200
    assert resp_open.json()["success"] is True

    with _db() as db:
        db.add(
            PlatformCapitalEvent(
                event_id="platcap_evt_1",
                idempotency_key="platcap:manual:1",
                profit_month_id="202603",
                delta_micro_usdc=777,
                source="manual_test_inflow",
                evidence_tx_hash="0x" + ("33" * 32),
                evidence_url=None,
            )
        )
        db.commit()

    resp = _client.get("/api/v1/platform/funding")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["total_raised_micro_usdc"] == 777
    assert data["open_round_raised_micro_usdc"] == 777
    assert data["contributors"] == []
    assert data["contributors_total_count"] == 0
    assert data["contributors_data_source"] == "ledger_fallback"
    assert data["unattributed_micro_usdc"] == 777
