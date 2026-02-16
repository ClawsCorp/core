from __future__ import annotations

import sys
from pathlib import Path

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
from src.models.reconciliation_report import ReconciliationReport


def test_alerts_endpoint_returns_envelope() -> None:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    session_local = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    Base.metadata.create_all(bind=engine)

    def _override_get_db():
        db: Session = session_local()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = _override_get_db
    client = TestClient(app, raise_server_exceptions=False)
    try:
        resp = client.get("/api/v1/alerts")
        assert resp.status_code == 200
        payload = resp.json()
        assert payload["success"] is True
        assert "items" in payload["data"]
        assert isinstance(payload["data"]["items"], list)
    finally:
        app.dependency_overrides.clear()


def test_alerts_skip_profit_deposit_missing_when_tx_outbox_disabled(monkeypatch) -> None:
    monkeypatch.setenv("TX_OUTBOX_ENABLED", "false")
    get_settings.cache_clear()

    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    session_local = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    Base.metadata.create_all(bind=engine)

    with session_local() as db:
        db.add(
            ReconciliationReport(
                profit_month_id="202602",
                revenue_sum_micro_usdc=120_000_000,
                expense_sum_micro_usdc=100_000_000,
                profit_sum_micro_usdc=20_000_000,
                distributor_balance_micro_usdc=0,
                delta_micro_usdc=-20_000_000,
                ready=False,
                blocked_reason="balance_mismatch",
                rpc_chain_id=84532,
                rpc_url_name="base_sepolia",
            )
        )
        db.commit()

    def _override_get_db():
        db: Session = session_local()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = _override_get_db
    client = TestClient(app, raise_server_exceptions=False)
    try:
        resp = client.get("/api/v1/alerts")
        assert resp.status_code == 200
        items = resp.json()["data"]["items"]
        alert_types = [str(x.get("alert_type")) for x in items if isinstance(x, dict)]
        assert "platform_profit_deposit_missing" not in alert_types
    finally:
        app.dependency_overrides.clear()
        get_settings.cache_clear()
