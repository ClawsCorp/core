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
from src.models.revenue_event import RevenueEvent

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


def test_oracle_revenue_event_accrues_marketing_fee(_client: TestClient, _db: sessionmaker[Session]) -> None:
    path = "/api/v1/oracle/revenue-events"
    body = json.dumps(
        {
            "profit_month_id": "202602",
            "project_id": None,
            "amount_micro_usdc": 1234,
            "tx_hash": "0x" + ("ab" * 32),
            "source": "platform_manual_receipt",
            "idempotency_key": "idem-rev-marketing-1",
            "evidence_url": "https://example.test/r/1",
        },
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    resp = _client.post(path, content=body, headers=_oracle_headers(path, body, "req-r1", idem="idem-h-r1"))
    assert resp.status_code == 200

    with _db() as db:
        assert db.query(RevenueEvent).count() == 1
        row = db.query(MarketingFeeAccrualEvent).first()
        assert row is not None
        assert row.bucket == "platform_revenue"
        assert row.fee_amount_micro_usdc == 12


def test_oracle_revenue_event_long_idempotency_key_keeps_marketing_key_bounded(
    _client: TestClient, _db: sessionmaker[Session]
) -> None:
    path = "/api/v1/oracle/revenue-events"
    source_idem = "k" * 255
    body = json.dumps(
        {
            "profit_month_id": "202602",
            "project_id": None,
            "amount_micro_usdc": 2000,
            "tx_hash": "0x" + ("cd" * 32),
            "source": "platform_manual_receipt",
            "idempotency_key": source_idem,
            "evidence_url": "https://example.test/r/2",
        },
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    resp = _client.post(path, content=body, headers=_oracle_headers(path, body, "req-r2", idem="idem-h-r2"))
    assert resp.status_code == 200

    with _db() as db:
        row = db.query(MarketingFeeAccrualEvent).first()
        assert row is not None
        assert row.fee_amount_micro_usdc == 20
        assert len(row.idempotency_key) <= 255
