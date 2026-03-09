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
from src.api.v1 import oracle_reputation

import src.models  # noqa: F401
from src.models.agent import Agent
from src.models.audit_log import AuditLog
from src.models.indexer_cursor import IndexerCursor
from src.models.observed_customer_referral import ObservedCustomerReferral
from src.models.observed_customer_referral_decision import ObservedCustomerReferralDecision
from src.models.observed_social_signal import ObservedSocialSignal
from src.models.observed_social_signal_decision import ObservedSocialSignalDecision
from src.models.reputation_event import ReputationEvent

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


def test_oracle_social_signal_creates_fixed_commercial_reputation(
    _client: TestClient, _db: sessionmaker[Session]
) -> None:
    with _db() as db:
        db.add(
            Agent(
                agent_id="ag_social",
                name="Signal Agent",
                capabilities_json="[]",
                wallet_address=None,
                api_key_hash="hash",
                api_key_last4="1111",
            )
        )
        db.commit()

    path = "/api/v1/oracle/reputation/social-signals"
    body = json.dumps(
        {
            "agent_id": "ag_social",
            "idempotency_key": "rep:social:1",
            "platform": "x",
            "signal_url": "https://x.example/post/1",
            "account_handle": "@signal_agent",
        }
    ).encode("utf-8")
    resp = _client.post(path, content=body, headers=_oracle_headers(path, body, "req-social", idem="rep:social:1"))
    assert resp.status_code == 200
    payload = resp.json()["data"]
    assert payload["source"] == "social_signal_verified"
    assert payload["delta_points"] == 10
    assert payload["ref_type"] == "social_signal"

    with _db() as db:
        row = db.query(ReputationEvent).filter(ReputationEvent.idempotency_key == "rep:social:1").one()
        assert row.source == "social_signal_verified"
        assert row.delta_points == 10


def test_oracle_social_signal_hashes_long_signal_url_into_safe_ref_id(
    _client: TestClient, _db: sessionmaker[Session]
) -> None:
    with _db() as db:
        db.add(
            Agent(
                agent_id="ag_social_long",
                name="Signal Agent Long",
                capabilities_json="[]",
                wallet_address=None,
                api_key_hash="hash",
                api_key_last4="3333",
            )
        )
        db.commit()

    path = "/api/v1/oracle/reputation/social-signals"
    long_url = "https://signals.example/" + ("x" * 220)
    body = json.dumps(
        {
            "agent_id": "ag_social_long",
            "idempotency_key": "rep:social:long:1",
            "platform": "x",
            "signal_url": long_url,
        }
    ).encode("utf-8")
    resp = _client.post(path, content=body, headers=_oracle_headers(path, body, "req-social-long", idem="rep:social:long:1"))
    assert resp.status_code == 200
    payload = resp.json()["data"]
    assert payload["ref_id"].startswith("url_sha256:")
    assert len(payload["ref_id"]) <= 128

    with _db() as db:
        row = db.query(ReputationEvent).filter(ReputationEvent.idempotency_key == "rep:social:long:1").one()
        assert row.ref_id.startswith("url_sha256:")


def test_oracle_customer_referral_supports_verified_and_paid_stages(
    _client: TestClient, _db: sessionmaker[Session]
) -> None:
    with _db() as db:
        db.add(
            Agent(
                agent_id="ag_referral",
                name="Referral Agent",
                capabilities_json="[]",
                wallet_address=None,
                api_key_hash="hash",
                api_key_last4="2222",
            )
        )
        db.commit()

    path = "/api/v1/oracle/reputation/customer-referrals"
    body_verified = json.dumps(
        {
            "agent_id": "ag_referral",
            "idempotency_key": "rep:ref:lead:1",
            "referral_id": "lead_1",
            "stage": "verified_lead",
            "evidence_url": "https://crm.example/leads/1",
        }
    ).encode("utf-8")
    resp_verified = _client.post(
        path,
        content=body_verified,
        headers=_oracle_headers(path, body_verified, "req-ref-1", idem="rep:ref:lead:1"),
    )
    assert resp_verified.status_code == 200
    assert resp_verified.json()["data"]["delta_points"] == 50

    body_paid = json.dumps(
        {
            "agent_id": "ag_referral",
            "idempotency_key": "rep:ref:paid:1",
            "referral_id": "lead_1",
            "stage": "paid_conversion",
            "evidence_url": "https://billing.example/invoices/1",
        }
    ).encode("utf-8")
    resp_paid = _client.post(
        path,
        content=body_paid,
        headers=_oracle_headers(path, body_paid, "req-ref-2", idem="rep:ref:paid:1"),
    )
    assert resp_paid.status_code == 200
    assert resp_paid.json()["data"]["delta_points"] == 150

    with _db() as db:
        rows = db.query(ReputationEvent).filter(ReputationEvent.agent_id == 1).order_by(ReputationEvent.id.asc()).all()
        assert len(rows) == 2
        assert rows[0].source == "customer_referral_verified"
        assert rows[0].delta_points == 50
        assert rows[1].source == "customer_referral_verified"
        assert rows[1].delta_points == 150


def test_observed_reputation_candidate_endpoints_are_append_only_and_idempotent(
    _client: TestClient, _db: sessionmaker[Session]
) -> None:
    with _db() as db:
        db.add(
            Agent(
                agent_id="ag_candidate",
                name="Candidate Agent",
                capabilities_json="[]",
                wallet_address=None,
                api_key_hash="hash",
                api_key_last4="4444",
            )
        )
        db.commit()

    social_path = "/api/v1/oracle/reputation/observed-social-signals"
    social_body = json.dumps(
        {
            "agent_id": "ag_candidate",
            "idempotency_key": "obs:social:1",
            "platform": "x",
            "signal_url": "https://example.com/post/42",
            "account_handle": "@candidate",
            "content_hash": "abc123",
        }
    ).encode("utf-8")
    social_resp = _client.post(
        social_path,
        content=social_body,
        headers=_oracle_headers(social_path, social_body, "req-obs-social-1", idem="obs:social:1"),
    )
    assert social_resp.status_code == 200
    assert social_resp.json()["data"]["platform"] == "x"

    social_resp_2 = _client.post(
        social_path,
        content=social_body,
        headers=_oracle_headers(social_path, social_body, "req-obs-social-2", idem="obs:social:1"),
    )
    assert social_resp_2.status_code == 200

    referral_path = "/api/v1/oracle/reputation/observed-customer-referrals"
    referral_body = json.dumps(
        {
            "agent_id": "ag_candidate",
            "idempotency_key": "obs:ref:1",
            "source_system": "hubspot",
            "external_ref": "lead-42",
            "stage": "lead_detected",
            "evidence_url": "https://crm.example/leads/42",
        }
    ).encode("utf-8")
    referral_resp = _client.post(
        referral_path,
        content=referral_body,
        headers=_oracle_headers(referral_path, referral_body, "req-obs-ref-1", idem="obs:ref:1"),
    )
    assert referral_resp.status_code == 200
    assert referral_resp.json()["data"]["source_system"] == "hubspot"

    with _db() as db:
        assert db.query(ObservedSocialSignal).count() == 1
        assert db.query(ObservedCustomerReferral).count() == 1


def test_observed_candidate_unknown_agent_is_audited_before_404(
    _client: TestClient, _db: sessionmaker[Session]
) -> None:
    path = "/api/v1/oracle/reputation/observed-social-signals"
    body = json.dumps(
        {
            "agent_id": "ag_missing",
            "idempotency_key": "obs:social:missing:1",
            "platform": "x",
            "signal_url": "https://example.com/post/missing",
        }
    ).encode("utf-8")
    resp = _client.post(path, content=body, headers=_oracle_headers(path, body, "req-obs-missing", idem="obs:social:missing:1"))
    assert resp.status_code == 404

    with _db() as db:
        audit = db.query(AuditLog).filter(AuditLog.idempotency_key == "obs:social:missing:1").first()
        assert audit is not None
        assert audit.actor_type == "oracle"


def test_sync_observed_candidates_promotes_only_eligible_rows(
    _client: TestClient, _db: sessionmaker[Session]
) -> None:
    with _db() as db:
        agent = Agent(
            agent_id="ag_sync",
            name="Sync Agent",
            capabilities_json="[]",
            wallet_address=None,
            api_key_hash="hash",
            api_key_last4="5555",
        )
        db.add(agent)
        db.flush()
        db.add_all(
            [
                ObservedSocialSignal(
                    signal_id="oss_1",
                    idempotency_key="obs:social:sync:1",
                    agent_id=agent.id,
                    platform="x",
                    signal_url="https://example.com/post/1",
                    account_handle="@sync",
                    content_hash="abc",
                    note=None,
                ),
                ObservedSocialSignal(
                    signal_id="oss_2",
                    idempotency_key="obs:social:sync:2",
                    agent_id=None,
                    platform="x",
                    signal_url="https://example.com/post/2",
                    account_handle="@sync",
                    content_hash="def",
                    note=None,
                ),
                ObservedCustomerReferral(
                    referral_event_id="ocr_1",
                    idempotency_key="obs:ref:sync:1",
                    agent_id=agent.id,
                    source_system="hubspot",
                    external_ref="lead_1",
                    stage="verified_lead",
                    evidence_url=None,
                    note=None,
                ),
                ObservedCustomerReferral(
                    referral_event_id="ocr_2",
                    idempotency_key="obs:ref:sync:2",
                    agent_id=agent.id,
                    source_system="hubspot",
                    external_ref="lead_2",
                    stage="lead_detected",
                    evidence_url=None,
                    note=None,
                ),
            ]
        )
        db.commit()

    social_sync_path = "/api/v1/oracle/reputation/social-signals/sync"
    social_sync_body = b"{}"
    social_resp = _client.post(
        social_sync_path,
        content=social_sync_body,
        headers=_oracle_headers(social_sync_path, social_sync_body, "req-sync-social", idem="sync-social-1"),
    )
    assert social_resp.status_code == 200
    social_data = social_resp.json()["data"]
    assert social_data["candidates_seen"] == 2
    assert social_data["eligible_candidates"] == 1
    assert social_data["reputation_events_created"] == 1
    assert social_data["skipped_unattributed"] == 1

    referral_sync_path = "/api/v1/oracle/reputation/customer-referrals/sync"
    referral_sync_body = b"{}"
    referral_resp = _client.post(
        referral_sync_path,
        content=referral_sync_body,
        headers=_oracle_headers(referral_sync_path, referral_sync_body, "req-sync-ref", idem="sync-ref-1"),
    )
    assert referral_resp.status_code == 200
    referral_data = referral_resp.json()["data"]
    assert referral_data["candidates_seen"] == 2
    assert referral_data["eligible_candidates"] == 1
    assert referral_data["reputation_events_created"] == 1
    assert referral_data["skipped_ineligible_stage"] == 1

    with _db() as db:
        rep_rows = db.query(ReputationEvent).order_by(ReputationEvent.id.asc()).all()
        assert len(rep_rows) == 2
        assert rep_rows[0].source == "social_signal_verified"
        assert rep_rows[1].source == "customer_referral_verified"
        social_decisions = db.query(ObservedSocialSignalDecision).order_by(ObservedSocialSignalDecision.id.asc()).all()
        referral_decisions = db.query(ObservedCustomerReferralDecision).order_by(ObservedCustomerReferralDecision.id.asc()).all()
        assert len(social_decisions) == 2
        assert social_decisions[0].decision_status == "promoted"
        assert social_decisions[1].reason_code == "unattributed"
        assert len(referral_decisions) == 2
        assert referral_decisions[0].decision_status == "promoted"
        assert referral_decisions[1].reason_code == "ineligible_stage"


def test_sync_observed_social_signals_uses_cursor_to_process_backlog(
    _client: TestClient, _db: sessionmaker[Session]
) -> None:
    with _db() as db:
        agent = Agent(
            agent_id="ag_backlog",
            name="Backlog Agent",
            capabilities_json="[]",
            wallet_address=None,
            api_key_hash="hash",
            api_key_last4="6666",
        )
        db.add(agent)
        db.flush()
        for index in range(501):
            db.add(
                ObservedSocialSignal(
                    signal_id=f"oss_backlog_{index}",
                    idempotency_key=f"obs:social:backlog:{index}",
                    agent_id=agent.id,
                    platform="x",
                    signal_url=f"https://example.com/post/{index}",
                    account_handle="@backlog",
                    content_hash=f"hash{index}",
                    note=None,
                )
            )
        db.commit()

    path = "/api/v1/oracle/reputation/social-signals/sync"
    body = b"{}"
    first = _client.post(path, content=body, headers=_oracle_headers(path, body, "req-backlog-1", idem="sync-backlog-1"))
    assert first.status_code == 200
    assert first.json()["data"]["candidates_seen"] == 500
    assert first.json()["data"]["reputation_events_created"] == 500

    second = _client.post(path, content=body, headers=_oracle_headers(path, body, "req-backlog-2", idem="sync-backlog-2"))
    assert second.status_code == 200
    assert second.json()["data"]["candidates_seen"] == 1
    assert second.json()["data"]["reputation_events_created"] == 1

    with _db() as db:
        assert db.query(ReputationEvent).filter(ReputationEvent.source == "social_signal_verified").count() == 501
        cursor = (
            db.query(IndexerCursor)
            .filter(IndexerCursor.cursor_key == "observed_social_signals", IndexerCursor.chain_id == 0)
            .first()
        )
        assert cursor is not None
        assert int(cursor.last_block_number) == 501


def test_sync_social_signals_skips_duplicate_identity_with_decision_trail(
    _client: TestClient, _db: sessionmaker[Session]
) -> None:
    with _db() as db:
        agent = Agent(
            agent_id="ag_dup_social",
            name="Duplicate Social",
            capabilities_json="[]",
            wallet_address=None,
            api_key_hash="hash",
            api_key_last4="7777",
        )
        db.add(agent)
        db.flush()
        db.add_all(
            [
                ObservedSocialSignal(
                    signal_id="oss_dup_1",
                    idempotency_key="obs:social:dup:1",
                    agent_id=agent.id,
                    platform="x",
                    signal_url="https://example.com/post/dup-1",
                    account_handle="@dup",
                    content_hash="same-hash",
                    note=None,
                ),
                ObservedSocialSignal(
                    signal_id="oss_dup_2",
                    idempotency_key="obs:social:dup:2",
                    agent_id=agent.id,
                    platform="x",
                    signal_url="https://example.com/post/dup-2",
                    account_handle="@dup",
                    content_hash="same-hash",
                    note=None,
                ),
            ]
        )
        db.commit()

    path = "/api/v1/oracle/reputation/social-signals/sync"
    body = b"{}"
    resp = _client.post(path, content=body, headers=_oracle_headers(path, body, "req-dup-social", idem="sync-dup-social"))
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["reputation_events_created"] == 1
    assert data["skipped_duplicate_identity"] == 1

    with _db() as db:
        assert db.query(ReputationEvent).filter(ReputationEvent.source == "social_signal_verified").count() == 1
        decisions = db.query(ObservedSocialSignalDecision).order_by(ObservedSocialSignalDecision.id.asc()).all()
        assert len(decisions) == 2
        assert decisions[0].decision_status == "promoted"
        assert decisions[1].reason_code == "duplicate_identity"


def test_social_signal_identity_key_bounds_long_content_hash() -> None:
    row = ObservedSocialSignal(
        signal_id="oss_bound_1",
        idempotency_key="obs:social:bound:1",
        agent_id=None,
        platform="p" * 64,
        signal_url=None,
        account_handle=None,
        content_hash="h" * 64,
        note=None,
    )
    identity_key = oracle_reputation._social_signal_identity_key(row)
    assert identity_key is not None
    assert len(identity_key) <= 128
    assert identity_key.startswith("content_hash:")


def test_reputation_sync_cursor_bootstrap_is_idempotent(_db: sessionmaker[Session]) -> None:
    with _db() as db:
        first = oracle_reputation._get_reputation_sync_cursor(db, "observed_social_signals")
        second = oracle_reputation._get_reputation_sync_cursor(db, "observed_social_signals")
        assert first == 0
        assert second == 0
        rows = (
            db.query(IndexerCursor)
            .filter(IndexerCursor.cursor_key == "observed_social_signals", IndexerCursor.chain_id == 0)
            .all()
        )
        assert len(rows) == 1
