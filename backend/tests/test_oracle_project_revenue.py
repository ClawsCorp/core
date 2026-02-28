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
from src.models.project import Project, ProjectStatus
from src.models.project_update import ProjectUpdate

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


def test_reconcile_project_revenue_publishes_ready_project_update(
    _client: TestClient,
    _db: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with _db() as db:
        db.add(
            Project(
                project_id="prj_rev_1",
                slug="rev-one",
                name="Revenue One",
                status=ProjectStatus.active,
                revenue_address="0x" + "1" * 40,
            )
        )
        db.commit()

    class _Balance:
        balance_micro_usdc = 0

    monkeypatch.setattr("src.api.v1.oracle_project_revenue.get_usdc_balance_micro_usdc", lambda _addr: _Balance())

    path = "/api/v1/oracle/projects/prj_rev_1/revenue/reconciliation"
    body = b""
    resp = _client.post(path, content=body, headers=_oracle_headers(path, body, "req-rev-1", idem="idem-rev-1"))
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["success"] is True
    assert payload["data"]["ready"] is True

    with _db() as db:
        update = db.query(ProjectUpdate).filter(ProjectUpdate.source_kind == "revenue_reconciliation_ready").first()
        assert update is not None
        assert update.update_type == "revenue"
        assert update.idempotency_key is not None
        assert len(update.idempotency_key) <= 255
