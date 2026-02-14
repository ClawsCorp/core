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
from src.core.security import generate_agent_api_key, hash_api_key
from src.main import app

import src.models  # noqa: F401
from src.models.agent import Agent


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


def _seed_agent(db: Session) -> str:
    agent_id = "ag_market"
    api_key = generate_agent_api_key(agent_id)
    db.add(
        Agent(
            agent_id=agent_id,
            name="MarketplaceAgent",
            capabilities_json="[]",
            wallet_address=None,
            api_key_hash=hash_api_key(api_key),
            api_key_last4=api_key[-4:],
        )
    )
    db.commit()
    return api_key


def test_marketplace_generate_is_idempotent_and_populates_proposal_detail(
    _client: TestClient, _db: sessionmaker[Session]
) -> None:
    with _db() as db:
        api_key = _seed_agent(db)

    # Create proposal.
    resp = _client.post(
        "/api/v1/agent/proposals",
        headers={"X-API-Key": api_key, "Idempotency-Key": "proposal:create:market:1"},
        json={"title": "My proposal", "description_md": "Details"},
    )
    assert resp.status_code == 200
    proposal_id = resp.json()["data"]["proposal_id"]

    # Generate marketplace items.
    gen_path = f"/api/v1/agent/marketplace/proposals/{proposal_id}/generate"
    resp = _client.post(
        gen_path,
        headers={"X-API-Key": api_key, "Idempotency-Key": "marketplace:gen:1"},
        json={},
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["proposal_id"] == proposal_id
    assert data["created_milestones_count"] == 3
    assert data["created_bounties_count"] == 3

    # Retry with a different Idempotency-Key should not duplicate.
    resp2 = _client.post(
        gen_path,
        headers={"X-API-Key": api_key, "Idempotency-Key": "marketplace:gen:2"},
        json={},
    )
    assert resp2.status_code == 200
    data2 = resp2.json()["data"]
    assert data2["created_milestones_count"] == 0
    assert data2["created_bounties_count"] == 0

    # Proposal detail should show milestones + related bounties.
    detail = _client.get(f"/api/v1/proposals/{proposal_id}")
    assert detail.status_code == 200
    body = detail.json()["data"]
    assert len(body["milestones"]) == 3
    assert len(body["related_bounties"]) == 3
    # Ensure bounties are linked to milestones.
    assert all(b.get("origin_milestone_id") for b in body["related_bounties"])

