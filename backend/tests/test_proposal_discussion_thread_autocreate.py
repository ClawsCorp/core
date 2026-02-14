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
from src.models.discussions import DiscussionThread


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
    agent_id = "ag_prop"
    api_key = generate_agent_api_key(agent_id)
    db.add(
        Agent(
            agent_id=agent_id,
            name="ProposalAgent",
            capabilities_json="[]",
            wallet_address=None,
            api_key_hash=hash_api_key(api_key),
            api_key_last4=api_key[-4:],
        )
    )
    db.commit()
    return api_key


def test_submit_autocreates_discussion_thread(_client: TestClient, _db: sessionmaker[Session]) -> None:
    with _db() as db:
        api_key = _seed_agent(db)

    # Create proposal (draft).
    resp = _client.post(
        "/api/v1/agent/proposals",
        headers={"X-API-Key": api_key, "Idempotency-Key": "proposal:create:1"},
        json={"title": "My proposal", "description_md": "Details"},
    )
    assert resp.status_code == 200
    proposal = resp.json()["data"]
    proposal_id = proposal["proposal_id"]
    assert proposal["discussion_thread_id"] is None

    # Submit proposal -> should ensure a deterministic discussion thread exists + is linked.
    resp = _client.post(
        f"/api/v1/agent/proposals/{proposal_id}/submit",
        headers={"X-API-Key": api_key, "Idempotency-Key": f"proposal:submit:{proposal_id}"},
        json={},
    )
    assert resp.status_code == 200
    submitted = resp.json()["data"]
    assert submitted["discussion_thread_id"] == f"dth_proposal_{proposal_id}"[:64]

    # Re-submit is idempotent and does not create another thread.
    resp = _client.post(
        f"/api/v1/agent/proposals/{proposal_id}/submit",
        headers={"X-API-Key": api_key, "Idempotency-Key": f"proposal:submit:{proposal_id}:2"},
        json={},
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["discussion_thread_id"] == submitted["discussion_thread_id"]

    with _db() as db:
        threads = db.query(DiscussionThread).filter(DiscussionThread.thread_id == submitted["discussion_thread_id"]).all()
        assert len(threads) == 1
        assert threads[0].ref_type == "proposal"
        assert threads[0].ref_id == proposal_id
