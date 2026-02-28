from __future__ import annotations

import hashlib
import hmac
import json
import sys
import time
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
from src.core.security import build_oracle_hmac_v2_payload
from src.main import app

import src.models  # noqa: F401
from src.models.billing_event import BillingEvent
from src.models.marketing_fee_accrual_event import MarketingFeeAccrualEvent
from src.models.observed_usdc_transfer import ObservedUsdcTransfer
from src.models.project import Project, ProjectStatus
from src.models.project_crypto_invoice import ProjectCryptoInvoice
from src.models.project_update import ProjectUpdate
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
    monkeypatch.setenv("ORACLE_ACCEPT_LEGACY_SIGNATURES", "false")

    # Patch block timestamp reader to avoid RPC in tests.
    import src.services.blockchain as blockchain

    def _fake_ts(_bn: int) -> datetime:
        return datetime(2026, 2, 1, 0, 0, 0, tzinfo=timezone.utc)

    monkeypatch.setattr(blockchain, "read_block_timestamp_utc", _fake_ts)

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


def test_billing_sync_creates_billing_and_revenue_events(_client: TestClient, _db: sessionmaker[Session]) -> None:
    revenue_addr = "0x00000000000000000000000000000000000000aa"

    db = _db()
    try:
        project = Project(
            project_id="prj_bill",
            slug="bill",
            name="Billing",
            description_md=None,
            status=ProjectStatus.active,
            proposal_id=None,
            origin_proposal_id=None,
            originator_agent_id=None,
            discussion_thread_id=None,
            treasury_wallet_address=None,
            treasury_address=None,
            revenue_wallet_address=None,
            revenue_address=revenue_addr,
            monthly_budget_micro_usdc=None,
            created_by_agent_id=None,
            approved_at=None,
        )
        db.add(project)
        db.flush()
        db.add(
            ObservedUsdcTransfer(
                chain_id=84532,
                token_address="0x0000000000000000000000000000000000000bbb",
                from_address="0x00000000000000000000000000000000000000cc",
                to_address=revenue_addr,
                amount_micro_usdc=1234,
                block_number=100,
                tx_hash="0x" + ("11" * 32),
                log_index=1,
            )
        )
        db.add(
            ProjectCryptoInvoice(
                invoice_id="inv_test_1",
                idempotency_key="invoice-idem-1",
                project_id=project.id,
                creator_agent_id=None,
                chain_id=84532,
                token_address="0x0000000000000000000000000000000000000bbb",
                payment_address=revenue_addr,
                payer_address="0x00000000000000000000000000000000000000cc",
                amount_micro_usdc=1234,
                description="Test invoice",
                status="pending",
                observed_transfer_id=None,
                paid_tx_hash=None,
                paid_log_index=None,
                paid_at=None,
            )
        )
        db.commit()
    finally:
        db.close()

    path = "/api/v1/oracle/billing/sync"
    body = b"{}"
    resp = _client.post(path, content=body, headers=_oracle_headers(path, body, "req-1", idem="idem-1"))
    assert resp.status_code == 200
    assert resp.json()["success"] is True
    assert resp.json()["data"]["billing_events_inserted"] == 1
    assert resp.json()["data"]["revenue_events_inserted"] == 1
    assert resp.json()["data"]["marketing_fee_events_inserted"] == 1
    assert resp.json()["data"]["marketing_fee_total_micro_usdc"] == 12
    assert resp.json()["data"]["invoices_paid"] == 1

    db = _db()
    try:
        assert db.query(BillingEvent).count() == 1
        rev = db.query(RevenueEvent).first()
        assert rev is not None
        assert rev.profit_month_id == "202602"
        assert rev.amount_micro_usdc == 1234
        inv = db.query(ProjectCryptoInvoice).filter(ProjectCryptoInvoice.invoice_id == "inv_test_1").first()
        assert inv is not None
        assert inv.status == "paid"
        assert inv.paid_tx_hash == "0x" + ("11" * 32)
        assert inv.paid_log_index == 1
        update = db.query(ProjectUpdate).first()
        updates = db.query(ProjectUpdate).order_by(ProjectUpdate.id.asc()).all()
        assert len(updates) == 2
        assert updates[0].update_type == "revenue"
        assert updates[0].source_kind == "crypto_invoice_paid"
        assert updates[0].source_ref == "inv_test_1"
        assert updates[1].update_type == "revenue"
        assert updates[1].source_kind == "billing_settlement"
        assert updates[1].source_ref == "inv_test_1"
        mfee = db.query(MarketingFeeAccrualEvent).first()
        assert mfee is not None
        assert mfee.bucket == "project_revenue"
        assert mfee.fee_amount_micro_usdc == 12
    finally:
        db.close()

    # Idempotent on second run.
    resp2 = _client.post(path, content=body, headers=_oracle_headers(path, body, "req-2", idem="idem-2"))
    assert resp2.status_code == 200
    assert resp2.json()["data"]["billing_events_inserted"] == 0
    assert resp2.json()["data"]["revenue_events_inserted"] == 0
    assert resp2.json()["data"]["marketing_fee_events_inserted"] == 0
    assert resp2.json()["data"]["marketing_fee_total_micro_usdc"] == 12
    assert resp2.json()["data"]["invoices_paid"] == 0
    db = _db()
    try:
        assert db.query(ProjectUpdate).count() == 2
    finally:
        db.close()
