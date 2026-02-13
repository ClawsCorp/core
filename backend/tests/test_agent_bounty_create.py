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
from src.main import app

import src.models  # noqa: F401
from src.models.agent import Agent
from src.models.audit_log import AuditLog
from src.models.bounty import Bounty, BountyFundingSource
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


def _seed_agent(db: Session) -> str:
    from src.core.security import generate_agent_api_key, hash_api_key

    agent_id = "ag_creator"
    api_key = generate_agent_api_key(agent_id)
    db.add(
        Agent(
            agent_id=agent_id,
            name="Creator",
            capabilities_json="[]",
            wallet_address=None,
            api_key_hash=hash_api_key(api_key),
            api_key_last4=api_key[-4:],
        )
    )
    db.commit()
    return api_key


def _seed_project(db: Session) -> None:
    db.add(
        Project(
            project_id="prj_1",
            slug="prj-1",
            name="Project 1",
            status=ProjectStatus.active,
        )
    )
    db.commit()


def test_agent_can_create_project_bounty_with_idempotency(_client: TestClient, _db: sessionmaker[Session]) -> None:
    with _db() as db:
        api_key = _seed_agent(db)
        _seed_project(db)

    payload = {
        "project_id": "prj_1",
        "funding_source": "project_capital",
        "title": "Do thing",
        "description_md": "Details",
        "amount_micro_usdc": 1_000_000,
        "idempotency_key": "bounty:create:1",
    }

    resp1 = _client.post("/api/v1/agent/bounties", headers={"X-API-Key": api_key}, json=payload)
    assert resp1.status_code == 200
    body1 = resp1.json()
    assert body1["success"] is True
    bounty_id = body1["data"]["bounty_id"]
    assert body1["data"]["project_id"] == "prj_1"
    assert body1["data"]["funding_source"] == "project_capital"

    resp2 = _client.post("/api/v1/agent/bounties", headers={"X-API-Key": api_key}, json=payload)
    assert resp2.status_code == 200
    body2 = resp2.json()
    assert body2["success"] is True
    assert body2["data"]["bounty_id"] == bounty_id

    with _db() as db:
        assert db.query(Bounty).count() == 1
        audit = (
            db.query(AuditLog)
            .filter(AuditLog.path == "/api/v1/agent/bounties", AuditLog.actor_type == "agent")
            .order_by(AuditLog.id.desc())
            .first()
        )
        assert audit is not None
        assert audit.idempotency_key == "bounty:create:1"


def test_agent_can_create_platform_bounty(_client: TestClient, _db: sessionmaker[Session]) -> None:
    with _db() as db:
        api_key = _seed_agent(db)

    payload = {
        "project_id": None,
        "funding_source": "platform_treasury",
        "title": "Platform work",
        "description_md": None,
        "amount_micro_usdc": 500_000,
    }

    resp = _client.post("/api/v1/agent/bounties", headers={"X-API-Key": api_key}, json=payload)
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    assert body["data"]["project_id"] is None
    assert body["data"]["funding_source"] == "platform_treasury"

    with _db() as db:
        bounty = db.query(Bounty).first()
        assert bounty is not None
        assert bounty.project_id is None
        assert bounty.funding_source == BountyFundingSource.platform_treasury


def test_agent_project_bounty_rejects_platform_treasury(_client: TestClient, _db: sessionmaker[Session]) -> None:
    with _db() as db:
        api_key = _seed_agent(db)
        _seed_project(db)

    payload = {
        "project_id": "prj_1",
        "funding_source": "platform_treasury",
        "title": "Bad source",
        "description_md": None,
        "amount_micro_usdc": 1,
    }

    resp = _client.post("/api/v1/agent/bounties", headers={"X-API-Key": api_key}, json=payload)
    assert resp.status_code == 400
