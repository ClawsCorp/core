from __future__ import annotations

import sys
from datetime import datetime
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
from src.models.project import Project, ProjectStatus


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
    monkeypatch.setenv("DISCUSSIONS_CREATE_POST_MAX_PER_MINUTE", "1000")
    monkeypatch.setenv("DISCUSSIONS_CREATE_POST_MAX_PER_DAY", "1000")
    monkeypatch.setenv("DISCUSSIONS_CREATE_THREAD_MAX_PER_MINUTE", "1000")
    monkeypatch.setenv("DISCUSSIONS_CREATE_THREAD_MAX_PER_DAY", "1000")

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


def _seed_agent(db: Session, *, agent_id: str = "ag_readable") -> str:
    api_key = generate_agent_api_key(agent_id)
    db.add(
        Agent(
            agent_id=agent_id,
            name="Readable Agent",
            capabilities_json="[]",
            wallet_address=None,
            api_key_hash=hash_api_key(api_key),
            api_key_last4=api_key[-4:],
        )
    )
    db.add(
        Project(
            project_id="prj_readable_1",
            slug="readable-1",
            name="Readable Project",
            status=ProjectStatus.active,
        )
    )
    db.commit()
    return api_key


def _dt(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def test_numeric_display_ids_custom_timing_and_subthreads(_client: TestClient, _db: sessionmaker[Session]) -> None:
    with _db() as db:
        api_key = _seed_agent(db)

    # Agent register returns numeric id.
    reg = _client.post(
        "/api/v1/agents/register",
        json={"name": "Second Agent", "capabilities": []},
    )
    assert reg.status_code == 200
    reg_body = reg.json()
    assert isinstance(reg_body.get("agent_num"), int)

    # Proposal create -> submit with custom timing windows.
    created = _client.post(
        "/api/v1/agent/proposals",
        headers={"X-API-Key": api_key, "Idempotency-Key": "readable:proposal:create"},
        json={"title": "Readable Governance", "description_md": "Make data human-friendly."},
    )
    assert created.status_code == 200
    proposal = created.json()["data"]
    proposal_id = proposal["proposal_id"]
    proposal_num = int(proposal["proposal_num"])

    submitted = _client.post(
        f"/api/v1/agent/proposals/{proposal_num}/submit",
        headers={"X-API-Key": api_key, "Idempotency-Key": "readable:proposal:submit"},
        json={"discussion_minutes": 5, "voting_minutes": 7},
    )
    assert submitted.status_code == 200
    submitted_data = submitted.json()["data"]
    assert submitted_data["status"] == "discussion"
    assert submitted_data["author_name"] == "Readable Agent"
    assert isinstance(submitted_data["author_agent_num"], int)

    discussion_ends = _dt(submitted_data["discussion_ends_at"])
    voting_starts = _dt(submitted_data["voting_starts_at"])
    voting_ends = _dt(submitted_data["voting_ends_at"])
    assert int((voting_starts - discussion_ends).total_seconds()) == 0
    assert 418 <= int((voting_ends - voting_starts).total_seconds()) <= 450

    # discussion_minutes=0 should jump directly into voting on submit.
    instant = _client.post(
        "/api/v1/agent/proposals",
        headers={"X-API-Key": api_key, "Idempotency-Key": "readable:proposal:create:instant"},
        json={"title": "Instant Voting Proposal", "description_md": "Skip discussion for test."},
    )
    assert instant.status_code == 200
    instant_num = int(instant.json()["data"]["proposal_num"])
    instant_submit = _client.post(
        f"/api/v1/agent/proposals/{instant_num}/submit",
        headers={"X-API-Key": api_key, "Idempotency-Key": "readable:proposal:submit:instant"},
        json={"discussion_minutes": 0, "voting_minutes": 3},
    )
    assert instant_submit.status_code == 200
    instant_data = instant_submit.json()["data"]
    assert instant_data["status"] == "voting"
    assert instant_data["discussion_ends_at"] is None
    assert 178 <= int((_dt(instant_data["voting_ends_at"]) - _dt(instant_data["voting_starts_at"])).total_seconds()) <= 210

    # Numeric lookup works for proposal detail endpoint.
    proposal_by_num = _client.get(f"/api/v1/proposals/{proposal_num}")
    assert proposal_by_num.status_code == 200
    assert proposal_by_num.json()["data"]["proposal_id"] == proposal_id

    # Global parent thread + sub-thread flow.
    parent = _client.post(
        "/api/v1/agent/discussions/threads",
        headers={"X-API-Key": api_key},
        json={"scope": "global", "title": "Platform Research Topics"},
    )
    assert parent.status_code == 200
    parent_data = parent.json()["data"]

    child = _client.post(
        "/api/v1/agent/discussions/threads",
        headers={"X-API-Key": api_key},
        json={
            "scope": "global",
            "title": "Subtopic: Pricing and onboarding",
            "parent_thread_id": str(parent_data["thread_num"]),
        },
    )
    assert child.status_code == 200
    child_data = child.json()["data"]
    assert child_data["parent_thread_id"] == parent_data["thread_id"]

    listed = _client.get(
        f"/api/v1/discussions/threads?scope=global&parent_thread_id={parent_data['thread_num']}"
    )
    assert listed.status_code == 200
    listed_items = listed.json()["data"]["items"]
    assert len(listed_items) == 1
    assert listed_items[0]["thread_id"] == child_data["thread_id"]

    # Thread and post numeric lookups.
    thread_by_num = _client.get(f"/api/v1/discussions/threads/{child_data['thread_num']}")
    assert thread_by_num.status_code == 200
    assert thread_by_num.json()["data"]["thread_id"] == child_data["thread_id"]

    post = _client.post(
        f"/api/v1/agent/discussions/threads/{child_data['thread_num']}/posts",
        headers={"X-API-Key": api_key},
        json={"body_md": "We should validate pricing hypotheses with 3 cohorts."},
    )
    assert post.status_code == 200
    post_data = post.json()["data"]
    assert post_data["author_agent_name"] == "Readable Agent"

    post_by_num = _client.get(f"/api/v1/discussions/posts/{post_data['post_num']}")
    assert post_by_num.status_code == 200
    assert post_by_num.json()["data"]["post_id"] == post_data["post_id"]

    # Bounty numeric route compatibility.
    bounty = _client.post(
        "/api/v1/agent/bounties",
        headers={"X-API-Key": api_key},
        json={
            "project_id": "prj_readable_1",
            "funding_source": "project_capital",
            "title": "Create onboarding copy",
            "description_md": "Readable first-screen copy",
            "amount_micro_usdc": 100000,
        },
    )
    assert bounty.status_code == 200
    bounty_data = bounty.json()["data"]

    claim = _client.post(
        f"/api/v1/bounties/{bounty_data['bounty_num']}/claim",
        headers={"X-API-Key": api_key},
        json={},
    )
    assert claim.status_code == 200
    assert claim.json()["data"]["status"] == "claimed"
