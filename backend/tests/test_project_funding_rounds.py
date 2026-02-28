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
from src.models.observed_usdc_transfer import ObservedUsdcTransfer
from src.models.project import Project, ProjectStatus

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


def test_project_funding_summary_uses_open_round_and_deposits(_client: TestClient, _db: sessionmaker[Session]) -> None:
    treasury = "0x00000000000000000000000000000000000000aa"
    from_addr = "0x00000000000000000000000000000000000000cc"

    with _db() as db:
        project = Project(
            project_id="prj_fund",
            slug="fund",
            name="Funding",
            description_md=None,
            status=ProjectStatus.fundraising,
            proposal_id=None,
            origin_proposal_id=None,
            originator_agent_id=None,
            discussion_thread_id=None,
            treasury_wallet_address=None,
            treasury_address=treasury,
            revenue_wallet_address=None,
            revenue_address=None,
            monthly_budget_micro_usdc=None,
            created_by_agent_id=None,
            approved_at=None,
        )
        db.add(project)
        db.commit()

    # Open a funding round.
    path_open = "/api/v1/oracle/projects/prj_fund/funding-rounds"
    body_open = json.dumps({"idempotency_key": "fr-open-1", "title": "Round 1", "cap_micro_usdc": 5000}).encode("utf-8")
    resp_open = _client.post(path_open, content=body_open, headers=_oracle_headers(path_open, body_open, "req-open", idem="idem-open"))
    assert resp_open.status_code == 200
    opened = resp_open.json()
    assert opened["success"] is True
    assert opened["data"]["status"] == "open"
    assert opened["data"]["cap_micro_usdc"] == 5000
    updates_after_open = _client.get("/api/v1/projects/prj_fund/updates")
    assert updates_after_open.status_code == 200
    open_updates = updates_after_open.json()["data"]["items"]
    assert len(open_updates) == 1
    assert open_updates[0]["update_type"] == "funding"
    assert open_updates[0]["source_ref"] == opened["data"]["round_id"]

    # Observe a treasury deposit and run sync.
    with _db() as db:
        db.add(
            ObservedUsdcTransfer(
                chain_id=84532,
                token_address="0x0000000000000000000000000000000000000bbb",
                from_address=from_addr,
                to_address=treasury,
                amount_micro_usdc=1234,
                block_number=100,
                tx_hash="0x" + ("22" * 32),
                log_index=1,
            )
        )
        db.commit()

    path_sync = "/api/v1/oracle/project-capital-events/sync"
    body_sync = b"{}"
    resp_sync = _client.post(path_sync, content=body_sync, headers=_oracle_headers(path_sync, body_sync, "req-sync", idem="idem-sync"))
    assert resp_sync.status_code == 200
    assert resp_sync.json()["success"] is True

    # Public funding summary should show progress and cap table for the open round.
    resp = _client.get("/api/v1/projects/prj_fund/funding")
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["success"] is True
    data = payload["data"]
    assert data["project_id"] == "prj_fund"
    assert data["open_round"] is not None
    assert data["open_round"]["title"] == "Round 1"
    assert data["open_round_raised_micro_usdc"] == 1234
    assert data["total_raised_micro_usdc"] == 1234
    assert data["contributors_total_count"] == 1
    assert data["contributors"][0]["address"] == from_addr.lower()
    assert data["contributors"][0]["amount_micro_usdc"] == 1234
    assert data["contributors_data_source"] == "observed_transfers"
    assert data["unattributed_micro_usdc"] == 0

    round_id = opened["data"]["round_id"]
    path_close = f"/api/v1/oracle/projects/prj_fund/funding-rounds/{round_id}/close"
    body_close = json.dumps({"idempotency_key": "fr-close-1"}).encode("utf-8")
    resp_close = _client.post(path_close, content=body_close, headers=_oracle_headers(path_close, body_close, "req-close", idem="idem-close"))
    assert resp_close.status_code == 200
    assert resp_close.json()["success"] is True
    updates_after_close = _client.get("/api/v1/projects/prj_fund/updates")
    assert updates_after_close.status_code == 200
    close_updates = updates_after_close.json()["data"]["items"]
    assert len(close_updates) == 3
    assert close_updates[0]["title"] == "Funding round closed: Round 1"
    assert close_updates[1]["title"] == "Capital deposit observed: 1234 micro-USDC"


def test_project_funding_summary_falls_back_to_ledger_inflow_when_indexer_lags(
    _client: TestClient, _db: sessionmaker[Session]
) -> None:
    treasury = "0x00000000000000000000000000000000000000ab"

    with _db() as db:
        project = Project(
            project_id="prj_fallback",
            slug="fund-fallback",
            name="Funding fallback",
            description_md=None,
            status=ProjectStatus.fundraising,
            proposal_id=None,
            origin_proposal_id=None,
            originator_agent_id=None,
            discussion_thread_id=None,
            treasury_wallet_address=None,
            treasury_address=treasury,
            revenue_wallet_address=None,
            revenue_address=None,
            monthly_budget_micro_usdc=None,
            created_by_agent_id=None,
            approved_at=None,
        )
        db.add(project)
        db.commit()

    # Open a funding round.
    path_open = "/api/v1/oracle/projects/prj_fallback/funding-rounds"
    body_open = json.dumps({"idempotency_key": "fr-open-fallback", "title": "Round F", "cap_micro_usdc": 9999}).encode("utf-8")
    resp_open = _client.post(path_open, content=body_open, headers=_oracle_headers(path_open, body_open, "req-open-fallback", idem="idem-open-fallback"))
    assert resp_open.status_code == 200
    assert resp_open.json()["success"] is True

    # Simulate append-only manual capital ingestion while observed transfers are not yet synced.
    path_event = "/api/v1/oracle/project-capital-events"
    body_event = json.dumps(
        {
            "event_id": None,
            "idempotency_key": "pcap-fallback-1",
            "profit_month_id": "202602",
            "project_id": "prj_fallback",
            "delta_micro_usdc": 777,
            "source": "e2e_manual_deposit",
            "evidence_tx_hash": "0x" + ("33" * 32),
            "evidence_url": None,
        }
    ).encode("utf-8")
    resp_event = _client.post(path_event, content=body_event, headers=_oracle_headers(path_event, body_event, "req-event-fallback", idem="idem-event-fallback"))
    assert resp_event.status_code == 200
    assert resp_event.json()["success"] is True

    # Funding summary remains truthful even without observed transfer rows.
    resp = _client.get("/api/v1/projects/prj_fallback/funding")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["total_raised_micro_usdc"] == 777
    assert data["open_round_raised_micro_usdc"] == 777
    assert data["contributors"] == []
    assert data["contributors_total_count"] == 0
    assert data["contributors_data_source"] == "ledger_fallback"
    assert data["unattributed_micro_usdc"] == 777
