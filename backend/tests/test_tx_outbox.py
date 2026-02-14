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


def test_tx_outbox_enqueue_claim_complete_happy_path(_client: TestClient) -> None:
    enqueue_path = "/api/v1/oracle/tx-outbox"
    enqueue_body = json.dumps(
        {"task_type": "noop", "payload": {"x": 1}, "idempotency_key": "idem-1"},
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    resp = _client.post(
        enqueue_path,
        content=enqueue_body,
        headers=_oracle_headers(enqueue_path, enqueue_body, "req-enq", idem="idem-enq"),
    )
    assert resp.status_code == 200
    task_id = resp.json()["data"]["task_id"]
    assert resp.json()["data"]["status"] == "pending"

    claim_path = f"/api/v1/oracle/tx-outbox/{task_id}/claim"
    claim_body = json.dumps({"worker_id": "w1"}, separators=(",", ":"), sort_keys=True).encode("utf-8")
    resp = _client.post(
        claim_path,
        content=claim_body,
        headers=_oracle_headers(claim_path, claim_body, "req-claim", idem="idem-claim"),
    )
    assert resp.status_code == 200
    assert resp.json()["success"] is True
    assert resp.json()["data"]["task"]["status"] == "processing"

    complete_path = f"/api/v1/oracle/tx-outbox/{task_id}/complete"
    complete_body = json.dumps({"status": "succeeded", "error_hint": None}, separators=(",", ":"), sort_keys=True).encode("utf-8")
    resp = _client.post(
        complete_path,
        content=complete_body,
        headers=_oracle_headers(complete_path, complete_body, "req-comp", idem="idem-comp"),
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["status"] == "succeeded"

