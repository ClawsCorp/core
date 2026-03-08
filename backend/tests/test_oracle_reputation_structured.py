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


def test_oracle_social_signal_creates_fixed_commercial_reputation(
    _client: TestClient, _db: sessionmaker[Session]
) -> None:
    with _db() as db:
        db.add(
            Agent(
                agent_id="ag_social",
                name="Signal Agent",
                capabilities_json="[]",
                wallet_address=None,
                api_key_hash="hash",
                api_key_last4="1111",
            )
        )
        db.commit()

    path = "/api/v1/oracle/reputation/social-signals"
    body = json.dumps(
        {
            "agent_id": "ag_social",
            "idempotency_key": "rep:social:1",
            "platform": "x",
            "signal_url": "https://x.example/post/1",
            "account_handle": "@signal_agent",
        }
    ).encode("utf-8")
    resp = _client.post(path, content=body, headers=_oracle_headers(path, body, "req-social", idem="rep:social:1"))
    assert resp.status_code == 200
    payload = resp.json()["data"]
    assert payload["source"] == "social_signal_verified"
    assert payload["delta_points"] == 10
    assert payload["ref_type"] == "social_signal"

    with _db() as db:
        row = db.query(ReputationEvent).filter(ReputationEvent.idempotency_key == "rep:social:1").one()
        assert row.source == "social_signal_verified"
        assert row.delta_points == 10


def test_oracle_social_signal_hashes_long_signal_url_into_safe_ref_id(
    _client: TestClient, _db: sessionmaker[Session]
) -> None:
    with _db() as db:
        db.add(
            Agent(
                agent_id="ag_social_long",
                name="Signal Agent Long",
                capabilities_json="[]",
                wallet_address=None,
                api_key_hash="hash",
                api_key_last4="3333",
            )
        )
        db.commit()

    path = "/api/v1/oracle/reputation/social-signals"
    long_url = "https://signals.example/" + ("x" * 220)
    body = json.dumps(
        {
            "agent_id": "ag_social_long",
            "idempotency_key": "rep:social:long:1",
            "platform": "x",
            "signal_url": long_url,
        }
    ).encode("utf-8")
    resp = _client.post(path, content=body, headers=_oracle_headers(path, body, "req-social-long", idem="rep:social:long:1"))
    assert resp.status_code == 200
    payload = resp.json()["data"]
    assert payload["ref_id"].startswith("url_sha256:")
    assert len(payload["ref_id"]) <= 128

    with _db() as db:
        row = db.query(ReputationEvent).filter(ReputationEvent.idempotency_key == "rep:social:long:1").one()
        assert row.ref_id.startswith("url_sha256:")


def test_oracle_customer_referral_supports_verified_and_paid_stages(
    _client: TestClient, _db: sessionmaker[Session]
) -> None:
    with _db() as db:
        db.add(
            Agent(
                agent_id="ag_referral",
                name="Referral Agent",
                capabilities_json="[]",
                wallet_address=None,
                api_key_hash="hash",
                api_key_last4="2222",
            )
        )
        db.commit()

    path = "/api/v1/oracle/reputation/customer-referrals"
    body_verified = json.dumps(
        {
            "agent_id": "ag_referral",
            "idempotency_key": "rep:ref:lead:1",
            "referral_id": "lead_1",
            "stage": "verified_lead",
            "evidence_url": "https://crm.example/leads/1",
        }
    ).encode("utf-8")
    resp_verified = _client.post(
        path,
        content=body_verified,
        headers=_oracle_headers(path, body_verified, "req-ref-1", idem="rep:ref:lead:1"),
    )
    assert resp_verified.status_code == 200
    assert resp_verified.json()["data"]["delta_points"] == 50

    body_paid = json.dumps(
        {
            "agent_id": "ag_referral",
            "idempotency_key": "rep:ref:paid:1",
            "referral_id": "lead_1",
            "stage": "paid_conversion",
            "evidence_url": "https://billing.example/invoices/1",
        }
    ).encode("utf-8")
    resp_paid = _client.post(
        path,
        content=body_paid,
        headers=_oracle_headers(path, body_paid, "req-ref-2", idem="rep:ref:paid:1"),
    )
    assert resp_paid.status_code == 200
    assert resp_paid.json()["data"]["delta_points"] == 150

    with _db() as db:
        rows = db.query(ReputationEvent).filter(ReputationEvent.agent_id == 1).order_by(ReputationEvent.id.asc()).all()
        assert len(rows) == 2
        assert rows[0].source == "customer_referral_verified"
        assert rows[0].delta_points == 50
        assert rows[1].source == "customer_referral_verified"
        assert rows[1].delta_points == 150
