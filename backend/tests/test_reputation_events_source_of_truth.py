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
    assert isinstance(r_sum.json()["data"]["agent_num"], int)
    assert r_sum.json()["data"]["agent_name"] == "Alice"

    r_lb = _client.get("/api/v1/reputation/leaderboard")
    assert r_lb.status_code == 200
    assert r_lb.json()["data"]["items"][0]["agent_name"] == "Alice"
    assert isinstance(r_lb.json()["data"]["items"][0]["agent_num"], int)

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
