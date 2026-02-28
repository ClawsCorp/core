from __future__ import annotations

import sys
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from src.api.v1.dependencies import require_agent_auth
from src.core.database import Base, get_db
from src.main import app

import src.models  # noqa: F401
from src.models.agent import Agent
from src.models.project import Project, ProjectStatus
from src.models.project_member import ProjectMember, ProjectMemberRole


def test_project_updates_create_and_list() -> None:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    session_local = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    Base.metadata.create_all(bind=engine)

    with session_local() as db:
        agent = Agent(
            agent_id="ag_updates_1",
            name="Updater",
            capabilities_json="[]",
            wallet_address=None,
            api_key_hash="hash",
            api_key_last4="1234",
        )
        db.add(agent)
        db.flush()
        project = Project(
            project_id="prj_updates_1",
            slug="updates-one",
            name="Updates One",
            description_md=None,
            status=ProjectStatus.active,
            proposal_id=None,
            origin_proposal_id=None,
            originator_agent_id=None,
            discussion_thread_id=None,
            treasury_wallet_address=None,
            treasury_address=None,
            revenue_wallet_address=None,
            revenue_address=None,
            monthly_budget_micro_usdc=None,
            created_by_agent_id=None,
            approved_at=None,
        )
        db.add(project)
        db.flush()
        db.add(
            ProjectMember(
                project_id=project.id,
                agent_id=agent.id,
                role=ProjectMemberRole.maintainer,
            )
        )
        db.commit()

    def _override_get_db():
        db: Session = session_local()
        try:
            yield db
        finally:
            db.close()

    def _override_agent_auth() -> Agent:
        with session_local() as db:
            return db.query(Agent).filter(Agent.agent_id == "ag_updates_1").one()

    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[require_agent_auth] = _override_agent_auth
    client = TestClient(app, raise_server_exceptions=False)
    try:
        create_resp = client.post(
            "/api/v1/agent/projects/prj_updates_1/updates",
            json={
                "title": "Delivery completed",
                "body_md": "Frontend and backend deliverables merged.",
                "update_type": "delivery",
                "source_kind": "delivery_receipt",
                "source_ref": "receipt:prj_updates_1",
                "idempotency_key": "upd:test:1",
            },
            headers={"X-Request-Id": "req-upd-1"},
        )
        assert create_resp.status_code == 200
        create_data = create_resp.json()["data"]
        assert create_data["project_id"] == "prj_updates_1"
        assert create_data["author_agent_id"] == "ag_updates_1"
        assert create_data["title"] == "Delivery completed"

        second_resp = client.post(
            "/api/v1/agent/projects/prj_updates_1/updates",
            json={
                "title": "Delivery completed",
                "body_md": "Frontend and backend deliverables merged.",
                "update_type": "delivery",
                "source_kind": "delivery_receipt",
                "source_ref": "receipt:prj_updates_1",
                "idempotency_key": "upd:test:1",
            },
            headers={"X-Request-Id": "req-upd-2"},
        )
        assert second_resp.status_code == 200
        assert second_resp.json()["data"]["update_id"] == create_data["update_id"]

        list_resp = client.get("/api/v1/projects/prj_updates_1/updates")
        assert list_resp.status_code == 200
        payload = list_resp.json()
        assert payload["success"] is True
        assert payload["data"]["total"] == 1
        item = payload["data"]["items"][0]
        assert item["title"] == "Delivery completed"
        assert item["source_kind"] == "delivery_receipt"
        assert item["source_ref"] == "receipt:prj_updates_1"
    finally:
        app.dependency_overrides.clear()
