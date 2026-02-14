from __future__ import annotations

import sys
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
from src.main import app

import src.models  # noqa: F401
from src.models.observed_usdc_transfer import ObservedUsdcTransfer


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
def _client(_db: sessionmaker[Session]) -> TestClient:
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


def test_stakers_endpoint_blocks_when_missing_address(_client: TestClient) -> None:
    resp = _client.get("/api/v1/stakers")
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["success"] is False
    assert payload["data"]["blocked_reason"] == "funding_pool_address_missing"


def test_stakers_endpoint_reports_net_stakes(_client: TestClient, _db: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch) -> None:
    pool = "0x9999999999999999999999999999999999999999"
    monkeypatch.setenv("FUNDING_POOL_CONTRACT_ADDRESS", pool)
    get_settings.cache_clear()

    with _db() as db:
        db.add(
            ObservedUsdcTransfer(
                chain_id=84532,
                token_address="0x0000000000000000000000000000000000000001",
                from_address="0x1111111111111111111111111111111111111111",
                to_address=pool,
                amount_micro_usdc=10,
                block_number=1,
                tx_hash="0x" + "11" * 32,
                log_index=0,
            )
        )
        db.add(
            ObservedUsdcTransfer(
                chain_id=84532,
                token_address="0x0000000000000000000000000000000000000001",
                from_address=pool,
                to_address="0x1111111111111111111111111111111111111111",
                amount_micro_usdc=4,
                block_number=2,
                tx_hash="0x" + "22" * 32,
                log_index=0,
            )
        )
        db.commit()

    resp = _client.get("/api/v1/stakers?limit=10")
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["success"] is True
    data = payload["data"]
    assert data["funding_pool_address"] == pool
    assert data["stakers_count"] == 1
    assert data["total_staked_micro_usdc"] == 6
    assert data["top"][0]["address"] == "0x1111111111111111111111111111111111111111"
    assert data["top"][0]["stake_micro_usdc"] == 6

