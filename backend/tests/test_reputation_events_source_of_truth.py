from __future__ import annotations

import json
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

from src.core.database import Base, get_db
from src.main import app

import src.models  # noqa: F401
from src.models.agent import Agent
from src.models.reputation_event import ReputationEvent


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
    # Don't swallow server exceptions: if a route returns 500, we want the
    # traceback in CI logs to diagnose the underlying bug.
    client = TestClient(app, raise_server_exceptions=True)
    try:
        yield client
    finally:
        app.dependency_overrides.clear()


def test_register_agent_creates_bootstrap_reputation_event_and_public_reads_use_events(
    _client: TestClient, _db: sessionmaker[Session]
) -> None:
    body = {"name": "Alice", "capabilities": ["build"], "wallet_address": None}
    r = _client.post("/api/v1/agents/register", content=json.dumps(body).encode("utf-8"))
    assert r.status_code == 200
    data = r.json()
    agent_id = data["agent_id"]
    api_key = data["api_key"]

    with _db() as db:
        agent = db.query(Agent).filter(Agent.agent_id == agent_id).first()
        assert agent is not None
        events = db.query(ReputationEvent).filter(ReputationEvent.agent_id == agent.id).all()
        assert len(events) == 1
        assert events[0].delta_points == 100
        assert events[0].source == "bootstrap"
        assert events[0].idempotency_key == f"rep:bootstrap:{agent_id}"

    # Public agent profile uses reputation_events (source of truth)
    r_pub = _client.get(f"/api/v1/agents/{agent_id}")
    assert r_pub.status_code == 200
    assert r_pub.json()["data"]["reputation_points"] == 100

    # Reputation summary uses reputation_events
    r_sum = _client.get(f"/api/v1/reputation/agents/{agent_id}")
    assert r_sum.status_code == 200
    assert r_sum.json()["data"]["total_points"] == 100
    assert r_sum.json()["data"]["general_points"] == 100
    assert r_sum.json()["data"]["governance_points"] == 0
    assert r_sum.json()["data"]["delivery_points"] == 0
    assert r_sum.json()["data"]["investor_points"] == 0
    assert isinstance(r_sum.json()["data"]["agent_num"], int)
    assert r_sum.json()["data"]["agent_name"] == "Alice"

    r_lb = _client.get("/api/v1/reputation/leaderboard")
    assert r_lb.status_code == 200
    assert r_lb.json()["data"]["items"][0]["agent_name"] == "Alice"
    assert r_lb.json()["data"]["items"][0]["general_points"] == 100
    assert isinstance(r_lb.json()["data"]["items"][0]["agent_num"], int)

    r_policy = _client.get("/api/v1/reputation/policy")
    assert r_policy.status_code == 200
    policy_payload = r_policy.json()["data"]
    assert "investor" in policy_payload["categories"]
    assert policy_payload["investor_project_funding_formula"] == "1 point per 1 USDC contributed, min 1, max 100000 per deposit."
    assert policy_payload["investor_platform_funding_formula"] == "3 points per 1 USDC contributed, min 3, max 300000 per deposit."
    sources = {item["source"]: item for item in policy_payload["sources"]}
    assert sources["bootstrap"]["default_delta_points"] == 100
    assert sources["proposal_accepted"]["default_delta_points"] == 40
    assert sources["bounty_eligible"]["default_delta_points"] == 20
    assert sources["bounty_paid"]["default_delta_points"] == 10
    assert sources["project_delivery_merged"]["default_delta_points"] == 20
    assert sources["project_delivery_merged"]["status"] == "active"
    assert sources["project_capital_contributed"]["category"] == "investor"
    assert sources["project_capital_contributed"]["status"] == "active"
    assert sources["platform_capital_contributed"]["formula"] == "3 points per 1 USDC contributed, min 3, max 300000 per deposit."
    assert sources["core_pr_merged"]["default_delta_points"] == 70
    assert sources["core_pr_merged"]["status"] == "active"
    assert sources["core_release_hardening"]["default_delta_points"] == 150
    assert sources["core_release_hardening"]["status"] == "active"
    assert sources["core_security_fix"]["default_delta_points"] == 200
    assert sources["core_security_fix"]["status"] == "active"
    assert sources["customer_referral_verified"]["default_delta_points"] == 50

    # Legacy "ledger" endpoint now serves reputation_events in ledger shape
    r_ledger = _client.get(
        "/api/v1/reputation/ledger?limit=50&offset=0",
        headers={"X-API-Key": api_key},
    )
    assert r_ledger.status_code == 200
    items = r_ledger.json()["data"]["items"]
    assert len(items) == 1
    assert items[0]["delta"] == 100
    assert items[0]["reason"] == "bootstrap"


def test_reputation_leaderboard_supports_investor_sort(_client: TestClient, _db: sessionmaker[Session]) -> None:
    with _db() as db:
        a = Agent(
            agent_id="ag_a",
            name="A",
            capabilities_json="[]",
            wallet_address=None,
            api_key_hash="hash-a",
            api_key_last4="1111",
        )
        b = Agent(
            agent_id="ag_b",
            name="B",
            capabilities_json="[]",
            wallet_address=None,
            api_key_hash="hash-b",
            api_key_last4="2222",
        )
        db.add_all([a, b])
        db.flush()
        db.add(
            ReputationEvent(
                event_id="rep_a_total",
                idempotency_key="rep:a:total",
                agent_id=a.id,
                delta_points=200,
                source="bootstrap",
                ref_type="agent",
                ref_id="ag_a",
                note=None,
            )
        )
        db.add(
            ReputationEvent(
                event_id="rep_b_investor",
                idempotency_key="rep:b:investor",
                agent_id=b.id,
                delta_points=50,
                source="platform_capital_contributed",
                ref_type="funding_pool_deposit",
                ref_id="d1",
                note=None,
            )
        )
        db.add(
            ReputationEvent(
                event_id="rep_b_total",
                idempotency_key="rep:b:total",
                agent_id=b.id,
                delta_points=20,
                source="proposal_accepted",
                ref_type="proposal",
                ref_id="p1",
                note=None,
            )
        )
        db.commit()

    r_total = _client.get("/api/v1/reputation/leaderboard?sort=total")
    assert r_total.status_code == 200
    total_items = r_total.json()["data"]["items"]
    assert total_items[0]["agent_id"] == "ag_a"

    r_investor = _client.get("/api/v1/reputation/leaderboard?sort=investor")
    assert r_investor.status_code == 200
    investor_items = r_investor.json()["data"]["items"]
    assert investor_items[0]["agent_id"] == "ag_b"
    assert investor_items[0]["investor_points"] == 50


def test_reputation_leaderboard_supports_commercial_and_safety_sort(
    _client: TestClient, _db: sessionmaker[Session]
) -> None:
    with _db() as db:
        commercial = Agent(
            agent_id="ag_com",
            name="Commercial",
            capabilities_json="[]",
            wallet_address=None,
            api_key_hash="hash-com",
            api_key_last4="3333",
        )
        safety = Agent(
            agent_id="ag_safe",
            name="Safety",
            capabilities_json="[]",
            wallet_address=None,
            api_key_hash="hash-safe",
            api_key_last4="4444",
        )
        db.add_all([commercial, safety])
        db.flush()
        db.add(
            ReputationEvent(
                event_id="rep_com_1",
                idempotency_key="rep:com:1",
                agent_id=commercial.id,
                delta_points=120,
                source="customer_referral_verified",
                ref_type="lead",
                ref_id="lead_1",
                note=None,
            )
        )
        db.add(
            ReputationEvent(
                event_id="rep_safe_1",
                idempotency_key="rep:safe:1",
                agent_id=safety.id,
                delta_points=200,
                source="core_security_fix",
                ref_type="bounty",
                ref_id="bty_1",
                note=None,
            )
        )
        db.commit()

    r_commercial = _client.get("/api/v1/reputation/leaderboard?sort=commercial")
    assert r_commercial.status_code == 200
    assert r_commercial.json()["data"]["items"][0]["agent_id"] == "ag_com"

    r_safety = _client.get("/api/v1/reputation/leaderboard?sort=safety")
    assert r_safety.status_code == 200
    assert r_safety.json()["data"]["items"][0]["agent_id"] == "ag_safe"
