from __future__ import annotations

import hashlib
import hmac
import json
import time
import sys
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


def _build_signed_request(secret: str, request_id: str, payload: dict[str, object], timestamp: str | None = None) -> tuple[bytes, dict[str, str]]:
    body = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    body_hash = hashlib.sha256(body).hexdigest()
    request_timestamp = timestamp or str(int(time.time()))

    signature_payload = build_oracle_hmac_v2_payload(
        request_timestamp,
        request_id,
        "POST",
        ORACLE_PATH,
        body_hash,
    )
    signature = _sign(secret, signature_payload)
    return body, {
        "Content-Type": "application/json",
        "X-Request-Timestamp": request_timestamp,
        "X-Request-Id": request_id,
        "X-Signature": signature,
    }


def test_oracle_missing_required_headers_is_audited(_client: TestClient, _db: sessionmaker[Session]) -> None:
    response = _client.post(ORACLE_PATH, json=_revenue_payload("idem-missing-headers"))
    assert response.status_code == 403

    with _db() as db:
        audit = _latest_oracle_audit(db)
        assert audit is not None
        assert audit.signature_status == "invalid"
        assert audit.error_hint == "missing_required_oracle_headers"


def test_oracle_invalid_signature_is_audited(_client: TestClient, _db: sessionmaker[Session]) -> None:
    payload = _revenue_payload("idem-invalid-signature")
    body, headers = _build_signed_request("wrong-secret", "req-invalid-sig", payload)

    response = _client.post(ORACLE_PATH, content=body, headers=headers)
    assert response.status_code == 403

    with _db() as db:
        audit = _latest_oracle_audit(db)
        assert audit is not None
        assert audit.signature_status == "invalid"
        assert audit.error_hint == "invalid_oracle_signature"


def test_oracle_stale_timestamp_is_audited(_client: TestClient, _db: sessionmaker[Session]) -> None:
    payload = _revenue_payload("idem-stale")
    stale_timestamp = str(int(time.time()) - 3600)
    body, headers = _build_signed_request("test-oracle-secret", "req-stale", payload, timestamp=stale_timestamp)

    response = _client.post(ORACLE_PATH, content=body, headers=headers)
    assert response.status_code == 403

    with _db() as db:
        audit = _latest_oracle_audit(db)
        assert audit is not None
        assert audit.signature_status == "stale"
        assert audit.error_hint == "stale_or_invalid_timestamp"


def test_oracle_valid_then_replay_is_audited_and_nonce_persisted(
    _client: TestClient,
    _db: sessionmaker[Session],
) -> None:
    request_id = "req-valid-then-replay"
    payload = _revenue_payload("idem-valid")
    body, headers = _build_signed_request("test-oracle-secret", request_id, payload)

    ok_response = _client.post(ORACLE_PATH, content=body, headers=headers)
    assert ok_response.status_code == 200

    with _db() as db:
        ok_audit = _latest_oracle_audit(db)
        assert ok_audit is not None
        assert ok_audit.signature_status == "ok"
        assert ok_audit.error_hint is None

        nonce = db.query(OracleNonce).filter(OracleNonce.request_id == request_id).first()
        assert nonce is not None

    replay_response = _client.post(ORACLE_PATH, content=body, headers=headers)
    assert replay_response.status_code == 409

    with _db() as db:
        replay_audit = _latest_oracle_audit(db)
        assert replay_audit is not None
        assert replay_audit.signature_status == "replay"
        assert replay_audit.error_hint == "replayed_request_id"
