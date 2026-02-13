from __future__ import annotations

import hashlib
import hmac
import sys
import time
from pathlib import Path

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

# Make `src` importable whether pytest runs from repo root or backend/.
BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from src.api.v1.dependencies import require_oracle_hmac
from src.core.config import get_settings
from src.core.database import Base, get_db
from src.core.security import build_oracle_hmac_v2_payload

# Ensure tables are registered on Base.metadata
from src.models.audit_log import AuditLog  # noqa: F401
from src.models.oracle_nonce import OracleNonce  # noqa: F401


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

    @app.post("/oracle-test")
    async def oracle_test(_: str = Depends(require_oracle_hmac)) -> dict[str, bool]:
        return {"ok": True}

    return app


@pytest.fixture(autouse=True)
def _isolate_settings_cache() -> None:
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_oracle_hmac_v2_replay_and_request_id_binding(monkeypatch: pytest.MonkeyPatch) -> None:
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

    app = _make_test_app(session_local)
    client = TestClient(app)

    body = b'{"hello":"world"}'
    body_hash = hashlib.sha256(body).hexdigest()
    timestamp = str(int(time.time()))
    request_id = "req-1"

    payload = build_oracle_hmac_v2_payload(
        timestamp,
        request_id,
        body_hash,
        method="POST",
        path="/oracle-test",
    )
    signature = _sign(secret, payload)

    resp_ok = client.post(
        "/oracle-test",
        content=body,
        headers={
            "X-Request-Timestamp": timestamp,
            "X-Request-Id": request_id,
            "X-Signature": signature,
            "Content-Type": "application/json",
        },
    )
    assert resp_ok.status_code == 200

    resp_invalid = client.post(
        "/oracle-test",
        content=body,
        headers={
            "X-Request-Timestamp": timestamp,
            "X-Request-Id": "req-2",
            "X-Signature": signature,
            "Content-Type": "application/json",
        },
    )
    assert resp_invalid.status_code == 403
    assert resp_invalid.json()["detail"] == "Invalid signature."

    resp_replay = client.post(
        "/oracle-test",
        content=body,
        headers={
            "X-Request-Timestamp": timestamp,
            "X-Request-Id": request_id,
            "X-Signature": signature,
            "Content-Type": "application/json",
        },
    )
    assert resp_replay.status_code == 409
    assert resp_replay.json()["detail"] == "Replay detected."
