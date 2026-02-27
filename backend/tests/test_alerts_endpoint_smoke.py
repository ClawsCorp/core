from __future__ import annotations

import sys
from datetime import datetime, timezone
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
from src.api.v1 import alerts as alerts_api

import src.models  # noqa: F401
from src.models.git_outbox import GitOutbox
from src.models.marketing_fee_accrual_event import MarketingFeeAccrualEvent
from src.models.reconciliation_report import ReconciliationReport
from src.models.tx_outbox import TxOutbox


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


def test_alerts_warn_when_safe_owner_address_missing(monkeypatch) -> None:
    monkeypatch.delenv("SAFE_OWNER_ADDRESS", raising=False)
    get_settings.cache_clear()

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
        alert_types = [str(x.get("alert_type")) for x in resp.json()["data"]["items"] if isinstance(x, dict)]
        assert "safe_owner_address_missing" in alert_types
    finally:
        app.dependency_overrides.clear()
        get_settings.cache_clear()


def test_alerts_warn_when_dividend_distributor_owner_mismatches_safe(monkeypatch) -> None:
    monkeypatch.setenv("SAFE_OWNER_ADDRESS", "0x00000000000000000000000000000000000000aa")
    get_settings.cache_clear()
    monkeypatch.setattr(
        alerts_api,
        "_fetch_dividend_distributor_owner",
        lambda _settings: ("0x00000000000000000000000000000000000000bb", None),
    )

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
        items = [x for x in resp.json()["data"]["items"] if isinstance(x, dict)]
        mismatches = [x for x in items if str(x.get("alert_type")) == "dividend_distributor_safe_owner_mismatch"]
        assert len(mismatches) == 1
        assert mismatches[0]["data"]["current_owner"].endswith("00bb")
    finally:
        app.dependency_overrides.clear()
        get_settings.cache_clear()


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


def test_alerts_do_not_report_missing_when_month_task_pending_with_amount_drift(monkeypatch) -> None:
    monkeypatch.setenv("TX_OUTBOX_ENABLED", "true")
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
        # Pending month-scoped deposit task exists, but with previous amount (delta changed).
        db.add(
            TxOutbox(
                task_id="txo_month_pending",
                idempotency_key="deposit_profit:202602:19000000",
                task_type="deposit_profit",
                payload_json='{"amount_micro_usdc":19000000,"profit_month_id":"202602","to_address":"0xabc"}',
                tx_hash=None,
                result_json=None,
                status="pending",
                attempts=1,
                last_error_hint=None,
                locked_at=None,
                locked_by=None,
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
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
        assert "platform_profit_deposit_pending" in alert_types
    finally:
        app.dependency_overrides.clear()
        get_settings.cache_clear()


def test_alerts_treat_zero_profit_positive_delta_as_carryover_info() -> None:
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
                profit_month_id="202603",
                revenue_sum_micro_usdc=0,
                expense_sum_micro_usdc=0,
                profit_sum_micro_usdc=0,
                distributor_balance_micro_usdc=20_000_000,
                delta_micro_usdc=20_000_000,
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
        assert "platform_settlement_not_ready" not in alert_types
        assert "platform_settlement_carryover_balance" in alert_types
    finally:
        app.dependency_overrides.clear()
        get_settings.cache_clear()


def test_alerts_include_git_outbox_stale_and_failed(monkeypatch) -> None:
    monkeypatch.setenv("GIT_OUTBOX_PENDING_MAX_AGE_SECONDS", "1")
    monkeypatch.setenv("GIT_OUTBOX_PROCESSING_MAX_AGE_SECONDS", "1")
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
            GitOutbox(
                task_id="gto_pending_old",
                idempotency_key="git:pending:old",
                task_type="create_app_surface_commit",
                payload_json='{"slug":"sunrise-ledger"}',
                result_json=None,
                branch_name=None,
                commit_sha=None,
                status="pending",
                attempts=1,
                last_error_hint=None,
                locked_at=None,
                locked_by=None,
                created_at=datetime(2020, 1, 1, tzinfo=timezone.utc),
                updated_at=datetime(2020, 1, 1, tzinfo=timezone.utc),
            )
        )
        db.add(
            GitOutbox(
                task_id="gto_failed_1",
                idempotency_key="git:failed:1",
                task_type="create_app_surface_commit",
                payload_json='{"slug":"aurora-notes"}',
                result_json='{"stage":"failed"}',
                branch_name=None,
                commit_sha=None,
                status="failed",
                attempts=3,
                last_error_hint="gh not authenticated",
                locked_at=None,
                locked_by=None,
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
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
        assert "git_outbox_pending_stale" in alert_types
        assert "git_outbox_failed" in alert_types
    finally:
        app.dependency_overrides.clear()
        get_settings.cache_clear()


def test_alerts_include_marketing_fee_accrued_when_pending_exists(monkeypatch) -> None:
    monkeypatch.setenv("MARKETING_FEE_BPS", "100")
    monkeypatch.setenv("MARKETING_TREASURY_ADDRESS", "0x00000000000000000000000000000000000000aa")
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
            MarketingFeeAccrualEvent(
                event_id="mfe_1",
                idempotency_key="mfee:test:pending",
                project_id=None,
                profit_month_id="202602",
                bucket="platform_revenue",
                source="test",
                gross_amount_micro_usdc=1000000,
                fee_amount_micro_usdc=10000,
                chain_id=None,
                tx_hash=None,
                log_index=None,
                evidence_url=None,
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
        marketing = [x for x in items if x.get("alert_type") == "marketing_fee_accrued"]
        assert len(marketing) == 1
        assert int(marketing[0]["data"]["pending_fee_micro_usdc"]) == 10000
    finally:
        app.dependency_overrides.clear()
        get_settings.cache_clear()


def test_alerts_skip_marketing_fee_accrued_when_fully_sent(monkeypatch) -> None:
    monkeypatch.setenv("MARKETING_FEE_BPS", "100")
    monkeypatch.setenv("MARKETING_TREASURY_ADDRESS", "0x00000000000000000000000000000000000000aa")
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
            MarketingFeeAccrualEvent(
                event_id="mfe_2",
                idempotency_key="mfee:test:sent",
                project_id=None,
                profit_month_id="202602",
                bucket="platform_revenue",
                source="test",
                gross_amount_micro_usdc=1000000,
                fee_amount_micro_usdc=10000,
                chain_id=None,
                tx_hash=None,
                log_index=None,
                evidence_url=None,
            )
        )
        db.add(
            TxOutbox(
                task_id="txo_marketing_sent",
                idempotency_key="deposit_marketing_fee:10000:0",
                task_type="deposit_marketing_fee",
                payload_json='{"amount_micro_usdc":10000,"to_address":"0x00000000000000000000000000000000000000aa"}',
                tx_hash="0xabc",
                result_json='{"stage":"submitted_only"}',
                status="succeeded",
                attempts=1,
                last_error_hint=None,
                locked_at=None,
                locked_by=None,
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
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
        assert "marketing_fee_accrued" not in alert_types
    finally:
        app.dependency_overrides.clear()
        get_settings.cache_clear()
