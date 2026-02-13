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

# Make `src` importable whether pytest runs from repo root or backend/.
BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from src.core.config import get_settings
from src.core.database import Base, get_db
from src.core.security import build_oracle_hmac_v2_payload
from src.main import app

# Ensure all tables are registered on Base.metadata
import src.models  # noqa: F401
from src.models.audit_log import AuditLog
from src.models.oracle_nonce import OracleNonce


ORACLE_PATH = "/api/v1/oracle/revenue-events"


def _sign(secret: str, payload: str) -> str:
    return hmac.new(secret.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).hexdigest()


def _revenue_payload(idempotency_key: str) -> dict[str, object]:
    return {
        "profit_month_id": "202501",
        "project_id": None,
        "amount_micro_usdc": 123456,
        "tx_hash": None,
        "source": "oracle",
        "idempotency_key": idempotency_key,
        "evidence_url": None,
    }


def _build_headers(
    secret: str,
    request_id: str,
    body: bytes,
    *,
    timestamp: str,
    method: str = "POST",
    path: str = ORACLE_PATH,
) -> dict[str, str]:
    body_hash = hashlib.sha256(body).hexdigest()
    payload = build_oracle_hmac_v2_payload(timestamp, request_id, method, path, body_hash)
    signature = _sign(secret, payload)
    return {
        "Content-Type": "application/json",
        "X-Request-Timestamp": timestamp,
        "X-Request-Id": request_id,
        "X-Signature": signature,
    }


def _latest_oracle_audit(db: Session) -> AuditLog | None:
    return (
        db.query(AuditLog)
        .filter(AuditLog.actor_type == "oracle", AuditLog.path == ORACLE_PATH)
        .order_by(AuditLog.id.desc())
        .first()
    )


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
    monkeypatch.setenv("ORACLE_HMAC_SECRET", "test-oracle-secret")
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
    client = TestClient(app)
    try:
        yield client
    finally:
        app.dependency_overrides.clear()


def test_oracle_hmac_v2_binding_replay_and_staleness(
    _client: TestClient,
    _db: sessionmaker[Session],
) -> None:
    secret = "test-oracle-secret"
    request_id = "req-v2-1"
    timestamp = str(int(time.time()))
    body = json.dumps(_revenue_payload("idem-v2-ok"), separators=(",", ":"), sort_keys=True).encode("utf-8")

    valid_headers = _build_headers(secret, request_id, body, timestamp=timestamp)
    ok_response = _client.post(ORACLE_PATH, content=body, headers=valid_headers)
    assert ok_response.status_code == 200

    with _db() as db:
        ok_audit = _latest_oracle_audit(db)
        assert ok_audit is not None
        assert ok_audit.signature_status == "ok"
        assert ok_audit.error_hint is None
        nonce = db.query(OracleNonce).filter(OracleNonce.request_id == request_id).first()
        assert nonce is not None

    reused_signature_headers = dict(valid_headers)
    reused_signature_headers["X-Request-Id"] = "req-v2-2"
    invalid_response = _client.post(ORACLE_PATH, content=body, headers=reused_signature_headers)
    assert invalid_response.status_code == 403

    with _db() as db:
        invalid_audit = _latest_oracle_audit(db)
        assert invalid_audit is not None
        assert invalid_audit.signature_status == "invalid"
        assert invalid_audit.error_hint == "invalid_oracle_signature"

    replay_response = _client.post(ORACLE_PATH, content=body, headers=valid_headers)
    assert replay_response.status_code == 409

    with _db() as db:
        replay_audit = _latest_oracle_audit(db)
        assert replay_audit is not None
        assert replay_audit.signature_status == "replay"
        assert replay_audit.error_hint == "replayed_request_id"

    stale_body = json.dumps(_revenue_payload("idem-v2-stale"), separators=(",", ":"), sort_keys=True).encode("utf-8")
    stale_headers = _build_headers(
        secret,
        "req-v2-stale",
        stale_body,
        timestamp=str(int(time.time()) - 3600),
    )
    stale_response = _client.post(ORACLE_PATH, content=stale_body, headers=stale_headers)
    assert stale_response.status_code == 403

    with _db() as db:
        stale_audit = _latest_oracle_audit(db)
        assert stale_audit is not None
        assert stale_audit.signature_status == "stale"
        assert stale_audit.error_hint == "stale_or_invalid_timestamp"


def test_oracle_hmac_v2_method_and_path_binding(_client: TestClient) -> None:
    secret = "test-oracle-secret"
    body = json.dumps(_revenue_payload("idem-v2-path"), separators=(",", ":"), sort_keys=True).encode("utf-8")
    timestamp = str(int(time.time()))

    wrong_path_headers = _build_headers(
        secret,
        "req-v2-path",
        body,
        timestamp=timestamp,
        method="POST",
        path="/api/v1/oracle/expense-events",
    )
    wrong_path_response = _client.post(ORACLE_PATH, content=body, headers=wrong_path_headers)
    assert wrong_path_response.status_code == 403

    wrong_method_headers = _build_headers(
        secret,
        "req-v2-method",
        body,
        timestamp=timestamp,
        method="GET",
        path=ORACLE_PATH,
    )
    wrong_method_response = _client.post(ORACLE_PATH, content=body, headers=wrong_method_headers)
    assert wrong_method_response.status_code == 403
