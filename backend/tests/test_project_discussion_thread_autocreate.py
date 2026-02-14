from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
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
from src.models.proposal import Proposal
from src.models.proposal import ProposalStatus
from src.models.project import Project
from src.models.vote import Vote


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
    agent_id = "ag_prj"
    api_key = generate_agent_api_key(agent_id)
    db.add(
        Agent(
            agent_id=agent_id,
            name="ProjectAgent",
            capabilities_json="[]",
            wallet_address=None,
            api_key_hash=hash_api_key(api_key),
            api_key_last4=api_key[-4:],
        )
    )
    db.commit()
    return api_key


def test_project_discussion_thread_created_on_proposal_activation(
    _client: TestClient,
    _db: sessionmaker[Session],
) -> None:
    with _db() as db:
        api_key = _seed_agent(db)

    # Create proposal.
    resp = _client.post(
        "/api/v1/agent/proposals",
        headers={"X-API-Key": api_key, "Idempotency-Key": "proposal:create:prj:1"},
        json={"title": "My project proposal", "description_md": "Details"},
    )
    assert resp.status_code == 200
    proposal_id = resp.json()["data"]["proposal_id"]

    # Submit -> moves to voting (discussion hours = 0).
    resp = _client.post(
        f"/api/v1/agent/proposals/{proposal_id}/submit",
        headers={"X-API-Key": api_key, "Idempotency-Key": f"proposal:submit:{proposal_id}"},
        json={},
    )
    assert resp.status_code == 200

    # Insert a yes vote directly (avoid relying on the vote endpoint here).
    with _db() as db:
        agent = db.query(Agent).filter(Agent.agent_id == "ag_prj").first()
        assert agent is not None
        proposal = db.query(Proposal).filter(Proposal.proposal_id == proposal_id).first()
        assert proposal is not None
        # Ensure we are in voting (submit may choose discussion depending on global settings).
        proposal.status = ProposalStatus.voting
        proposal.discussion_ends_at = None
        # Force the voting window to be safely in the past regardless of sqlite tz behavior.
        proposal.voting_starts_at = datetime(2000, 1, 1, tzinfo=timezone.utc)
        proposal.voting_ends_at = datetime(2000, 1, 2, tzinfo=timezone.utc)
        db.add(Vote(proposal_id=proposal.id, voter_agent_id=agent.id, value=1))
        proposal.yes_votes_count = 1
        proposal.no_votes_count = 0
        db.commit()

    # Finalize -> activates project.
    resp = _client.post(
        f"/api/v1/agent/proposals/{proposal_id}/finalize",
        headers={"X-API-Key": api_key, "Idempotency-Key": f"proposal:finalize:{proposal_id}"},
        json={},
    )
    assert resp.status_code == 200, resp.text
    resulting_project_id = resp.json()["data"]["resulting_project_id"]
    assert resulting_project_id is not None

    with _db() as db:
        project = db.query(Project).filter(Project.project_id == resulting_project_id).first()
        assert project is not None
        assert project.discussion_thread_id is not None
        thread = db.query(DiscussionThread).filter(DiscussionThread.thread_id == project.discussion_thread_id).first()
        assert thread is not None
        assert thread.scope == "project"
