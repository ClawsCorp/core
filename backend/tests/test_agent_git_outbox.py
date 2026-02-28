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

from src.core.config import get_settings
from src.core.database import Base, get_db
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


def _register_agent(client: TestClient, *, name: str) -> str:
    request_id = f"req-{name.lower().replace(' ', '-')}"
    resp = client.post(
        "/api/v1/agents/register",
        content=json.dumps({"name": name, "capabilities": []}).encode("utf-8"),
        headers={"Content-Type": "application/json", "X-Request-ID": request_id},
    )
    assert resp.status_code == 200
    return str(resp.json()["api_key"])


def test_agent_can_enqueue_and_list_project_git_tasks(_client: TestClient, _db: sessionmaker[Session]) -> None:
    owner_key = _register_agent(_client, name="Owner Agent")
    outsider_key = _register_agent(_client, name="Outsider Agent")

    with _db() as db:
        owner = db.query(Agent).filter(Agent.agent_id == owner_key.split(".")[0]).first()
        assert owner is not None
        project = Project(
            project_id="prj_git_1",
            slug="git-1",
            name="Git Project",
            description_md=None,
            status=ProjectStatus.active,
            proposal_id=None,
            origin_proposal_id=None,
            originator_agent_id=owner.id,
            discussion_thread_id=None,
            treasury_wallet_address=None,
            treasury_address=None,
            revenue_wallet_address=None,
            revenue_address=None,
            monthly_budget_micro_usdc=None,
            created_by_agent_id=owner.id,
            approved_at=None,
        )
        db.add(project)
        db.commit()
        project_num = int(project.id)

    enqueue = _client.post(
        "/api/v1/agent/projects/prj_git_1/git-outbox/surface-commit",
        headers={"Content-Type": "application/json", "X-API-Key": owner_key},
        json={
            "slug": "aurora-notes",
            "open_pr": False,
            "surface_title": "Aurora Notes",
            "surface_tagline": "Team writing space",
            "surface_description": "A focused environment for sprint notes and product decisions.",
            "cta_label": "Open Aurora Hub",
            "cta_href": "/projects/prj_git_1",
        },
    )
    assert enqueue.status_code == 200
    task = enqueue.json()["data"]
    assert task["task_type"] == "create_app_surface_commit"
    assert task["project_num"] == project_num
    assert task["requested_by_agent_num"] is not None
    assert task["payload"]["slug"] == "aurora-notes"
    assert task["payload"]["open_pr"] is False
    assert task["payload"]["surface_title"] == "Aurora Notes"
    assert task["payload"]["surface_tagline"] == "Team writing space"
    assert task["payload"]["cta_label"] == "Open Aurora Hub"
    assert task["payload"]["cta_href"] == "/projects/prj_git_1"
    assert isinstance(task["payload"]["pr_title"], str)
    assert "Checklist" in str(task["payload"]["pr_body"])

    listed = _client.get(
        f"/api/v1/agent/projects/{project_num}/git-outbox",
        headers={"X-API-Key": owner_key},
    )
    assert listed.status_code == 200
    body = listed.json()["data"]
    assert body["total"] == 1
    assert body["items"][0]["task_id"] == task["task_id"]

    blocked = _client.get(
        "/api/v1/agent/projects/prj_git_1/git-outbox",
        headers={"X-API-Key": outsider_key},
    )
    assert blocked.status_code == 403
    assert "project_access_denied" in blocked.text


def test_agent_git_outbox_defaults_open_pr_true(_client: TestClient, _db: sessionmaker[Session]) -> None:
    owner_key = _register_agent(_client, name="Owner Two")
    with _db() as db:
        owner = db.query(Agent).filter(Agent.agent_id == owner_key.split(".")[0]).first()
        assert owner is not None
        db.add(
            Project(
                project_id="prj_git_2",
                slug="git-2",
                name="Nova Index",
                description_md=None,
                status=ProjectStatus.active,
                proposal_id=None,
                origin_proposal_id=None,
                originator_agent_id=owner.id,
                discussion_thread_id=None,
                treasury_wallet_address=None,
                treasury_address=None,
                revenue_wallet_address=None,
                revenue_address=None,
                monthly_budget_micro_usdc=None,
                created_by_agent_id=owner.id,
                approved_at=None,
            )
        )
        db.commit()

    enqueue = _client.post(
        "/api/v1/agent/projects/prj_git_2/git-outbox/surface-commit",
        headers={"Content-Type": "application/json", "X-API-Key": owner_key},
        json={"slug": "nova-dashboard"},
    )
    assert enqueue.status_code == 200
    payload = enqueue.json()["data"]["payload"]
    assert payload["open_pr"] is True
    assert "Nova Index" in str(payload["pr_title"])
    assert "Checklist" in str(payload["pr_body"])


def test_agent_git_outbox_invalid_cta_href_rejected(_client: TestClient, _db: sessionmaker[Session]) -> None:
    owner_key = _register_agent(_client, name="Owner Three")
    with _db() as db:
        owner = db.query(Agent).filter(Agent.agent_id == owner_key.split(".")[0]).first()
        assert owner is not None
        db.add(
            Project(
                project_id="prj_git_3",
                slug="git-3",
                name="Sky Relay",
                description_md=None,
                status=ProjectStatus.active,
                proposal_id=None,
                origin_proposal_id=None,
                originator_agent_id=owner.id,
                discussion_thread_id=None,
                treasury_wallet_address=None,
                treasury_address=None,
                revenue_wallet_address=None,
                revenue_address=None,
                monthly_budget_micro_usdc=None,
                created_by_agent_id=owner.id,
                approved_at=None,
            )
        )
        db.commit()

    enqueue = _client.post(
        "/api/v1/agent/projects/prj_git_3/git-outbox/surface-commit",
        headers={"Content-Type": "application/json", "X-API-Key": owner_key},
        json={"slug": "sky-relay", "cta_href": "javascript:alert(1)"},
    )
    assert enqueue.status_code == 400
    assert "invalid_cta_href" in enqueue.text


def test_agent_can_enqueue_backend_artifact_git_task(_client: TestClient, _db: sessionmaker[Session]) -> None:
    owner_key = _register_agent(_client, name="Owner Four")
    with _db() as db:
        owner = db.query(Agent).filter(Agent.agent_id == owner_key.split(".")[0]).first()
        assert owner is not None
        db.add(
            Project(
                project_id="prj_git_4",
                slug="git-4",
                name="Pulse Ledger",
                description_md=None,
                status=ProjectStatus.active,
                proposal_id=None,
                origin_proposal_id=None,
                originator_agent_id=owner.id,
                discussion_thread_id=None,
                treasury_wallet_address=None,
                treasury_address=None,
                revenue_wallet_address=None,
                revenue_address=None,
                monthly_budget_micro_usdc=None,
                created_by_agent_id=owner.id,
                approved_at=None,
            )
        )
        db.commit()

    enqueue = _client.post(
        "/api/v1/agent/projects/prj_git_4/git-outbox/backend-artifact-commit",
        headers={"Content-Type": "application/json", "X-API-Key": owner_key},
        json={
            "slug": "pulse-ledger",
            "artifact_title": "Pulse Ledger backend artifact",
            "artifact_summary": "Maps the minimum API contract and safety checks.",
            "endpoint_paths": ["/api/v1/projects/prj_git_4", "/api/v1/projects/prj_git_4/funding"],
            "open_pr": False,
        },
    )
    assert enqueue.status_code == 200
    task = enqueue.json()["data"]
    assert task["task_type"] == "create_project_backend_artifact_commit"
    assert task["payload"]["slug"] == "pulse-ledger"
    assert task["payload"]["artifact_title"] == "Pulse Ledger backend artifact"
    assert task["payload"]["open_pr"] is False
    assert task["payload"]["endpoint_paths"] == ["/api/v1/projects/prj_git_4", "/api/v1/projects/prj_git_4/funding"]
    assert "Checklist" in str(task["payload"]["pr_body"])
