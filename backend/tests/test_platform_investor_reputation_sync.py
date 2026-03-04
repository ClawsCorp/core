from __future__ import annotations

import hashlib
import hmac
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


def test_platform_investor_reputation_sync_blocks_when_funding_pool_missing(_client: TestClient) -> None:
    path = "/api/v1/oracle/platform-capital/reputation-sync"
    body = b"{}"
    resp = _client.post(path, content=body, headers=_oracle_headers(path, body, "req-missing", idem="idem-missing"))
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["success"] is False
    assert payload["blocked_reason"] == "funding_pool_address_missing"


def test_platform_investor_reputation_sync_awards_registered_wallet_once(
    _client: TestClient, _db: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch
) -> None:
    pool = "0x9999999999999999999999999999999999999999"
    wallet = "0x1111111111111111111111111111111111111111"
    monkeypatch.setenv("FUNDING_POOL_CONTRACT_ADDRESS", pool)
    get_settings.cache_clear()

    with _db() as db:
        db.add(
            Agent(
                agent_id="ag_platform_investor",
                name="Platform Investor",
                capabilities_json="[]",
                wallet_address=wallet,
                api_key_hash="hash",
                api_key_last4="1111",
            )
        )
        db.add(
            ObservedUsdcTransfer(
                chain_id=84532,
                token_address="0x0000000000000000000000000000000000000001",
                from_address=wallet,
                to_address=pool,
                amount_micro_usdc=550_000,
                block_number=10,
                tx_hash="0x" + "11" * 32,
                log_index=0,
            )
        )
        db.commit()

    path = "/api/v1/oracle/platform-capital/reputation-sync"
    body = b"{}"
    resp = _client.post(path, content=body, headers=_oracle_headers(path, body, "req-1", idem="idem-1"))
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["transfers_seen"] == 1
    assert data["reputation_events_created"] == 1
    assert data["recognized_investor_transfers"] == 1

    with _db() as db:
        rows = db.query(ReputationEvent).all()
        assert len(rows) == 1
        assert rows[0].source == "platform_capital_contributed"
        assert rows[0].delta_points == 3

    resp_2 = _client.post(path, content=body, headers=_oracle_headers(path, body, "req-2", idem="idem-2"))
    assert resp_2.status_code == 200
    data_2 = resp_2.json()["data"]
    assert data_2["reputation_events_created"] == 0
    assert data_2["recognized_investor_transfers"] == 0

    with _db() as db:
        assert db.query(ReputationEvent).count() == 1
