from __future__ import annotations

import sys
from datetime import datetime, timezone
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
from src.models.indexer_cursor import IndexerCursor
from src.models.platform_capital_event import PlatformCapitalEvent
from src.models.platform_capital_reconciliation_report import PlatformCapitalReconciliationReport


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


def test_stats_includes_project_capital_reconciliation_max_age_seconds(
    _client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PROJECT_CAPITAL_RECONCILIATION_MAX_AGE_SECONDS", "3600")
    get_settings.cache_clear()

    r1 = _client.get("/api/v1/stats")
    assert r1.status_code == 200
    payload1 = r1.json()
    assert payload1["success"] is True
    assert payload1["data"]["default_chain_id"] == 84532
    assert payload1["data"]["project_capital_reconciliation_max_age_seconds"] == 3600
    assert payload1["data"]["platform_capital_reconciliation_max_age_seconds"] == 3600
    etag1 = r1.headers.get("ETag")
    assert etag1 is not None

    monkeypatch.setenv("PROJECT_CAPITAL_RECONCILIATION_MAX_AGE_SECONDS", "7200")
    get_settings.cache_clear()

    r2 = _client.get("/api/v1/stats")
    assert r2.status_code == 200
    payload2 = r2.json()
    assert payload2["data"]["project_capital_reconciliation_max_age_seconds"] == 7200
    etag2 = r2.headers.get("ETag")
    assert etag2 is not None
    assert etag2 != etag1


def test_stats_includes_platform_capital_summary(
    _client: TestClient,
    _db: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PLATFORM_CAPITAL_RECONCILIATION_MAX_AGE_SECONDS", "1800")
    get_settings.cache_clear()

    with _db() as db:
        db.add(
            PlatformCapitalEvent(
                event_id="platcap_1",
                idempotency_key="platcap:test:1",
                profit_month_id="202603",
                delta_micro_usdc=3_000_000,
                source="seed",
                evidence_tx_hash="0x" + "1" * 64,
                evidence_url="seed",
            )
        )
        db.add(
            PlatformCapitalReconciliationReport(
                funding_pool_address="0x" + "a" * 40,
                ledger_balance_micro_usdc=3_000_000,
                onchain_balance_micro_usdc=3_000_000,
                delta_micro_usdc=0,
                ready=True,
                blocked_reason=None,
                computed_at=datetime.now(timezone.utc),
            )
        )
        db.commit()

    response = _client.get("/api/v1/stats")
    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    data = payload["data"]
    assert data["platform_capital_reconciliation_max_age_seconds"] == 1800
    assert data["platform_capital_ledger_balance_micro_usdc"] == 3_000_000
    assert data["platform_capital_spendable_balance_micro_usdc"] == 3_000_000
    assert data["platform_capital_reconciliation_ready"] is True
    assert data["platform_capital_reconciliation_delta_micro_usdc"] == 0
    assert data["platform_capital_reconciliation_computed_at"] is not None


def test_stats_includes_configured_default_chain_id(
    _client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DEFAULT_CHAIN_ID", "8453")
    get_settings.cache_clear()

    response = _client.get("/api/v1/stats")
    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    assert payload["data"]["default_chain_id"] == 8453


def test_settings_prefers_blockchain_rpc_url_alias(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("BLOCKCHAIN_RPC_URL", "https://rpc.example.invalid")
    monkeypatch.setenv("BASE_SEPOLIA_RPC_URL", "https://legacy.example.invalid")
    get_settings.cache_clear()

    settings = get_settings()
    assert settings.blockchain_rpc_url == "https://rpc.example.invalid"
    assert settings.base_sepolia_rpc_url == "https://rpc.example.invalid"
    assert settings.blockchain_rpc_env_name == "BLOCKCHAIN_RPC_URL"


def test_indexer_status_reports_degraded_runtime_state(
    _client: TestClient,
    _db: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("INDEXER_LOOKBACK_BLOCKS", "9")
    monkeypatch.setenv("INDEXER_MIN_LOOKBACK_BLOCKS", "5")
    monkeypatch.setenv("INDEXER_CURSOR_MAX_AGE_SECONDS", "300")
    monkeypatch.setenv("INDEXER_DEGRADED_MAX_AGE_SECONDS", "900")
    get_settings.cache_clear()

    with _db() as db:
        db.add(
            IndexerCursor(
                cursor_key="usdc_transfers",
                chain_id=84532,
                last_block_number=123,
                last_scan_window_blocks=5,
                last_error_hint="eth_getLogs_range",
                degraded_since=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
            )
        )
        db.commit()

    resp = _client.get("/api/v1/indexer/status")
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["success"] is True
    assert payload["data"]["cursor_key"] == "usdc_transfers"
    assert payload["data"]["degraded"] is True
    assert payload["data"]["lookback_blocks_configured"] == 9
    assert payload["data"]["min_lookback_blocks_configured"] == 5
    assert payload["data"]["last_scan_window_blocks"] == 5
