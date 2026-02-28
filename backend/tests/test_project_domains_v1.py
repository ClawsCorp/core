from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
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
from src.models.project import Project, ProjectStatus
from src.models.project_domain import ProjectDomain


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

    # Monkeypatch DNS resolver to return the expected token.
    import src.services.project_domains as project_domains

    def _fake_resolve_txt_values(_name: str) -> list[str]:
        return ["token_ok"]

    monkeypatch.setattr(project_domains, "resolve_txt_values", _fake_resolve_txt_values)

    client = TestClient(app, raise_server_exceptions=False)
    try:
        yield client
    finally:
        app.dependency_overrides.clear()


def _register_agent(client: TestClient) -> str:
    resp = client.post(
        "/api/v1/agents/register",
        content=json.dumps({"name": "A", "capabilities": [], "wallet_address": None}).encode("utf-8"),
        headers={"Content-Type": "application/json", "X-Request-ID": "req-1"},
    )
    assert resp.status_code == 200
    return resp.json()["api_key"]


def test_project_domain_create_list_verify(_client: TestClient, _db: sessionmaker[Session]) -> None:
    api_key = _register_agent(_client)

    db = _db()
    try:
        p = Project(
            project_id="prj_dom",
            slug="dom",
            name="Dom",
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
            approved_at=datetime.now(timezone.utc),
        )
        db.add(p)
        db.commit()
    finally:
        db.close()

    # Create domain
    resp = _client.post(
        "/api/v1/agent/projects/prj_dom/domains",
        content=json.dumps({"domain": "example.com"}).encode("utf-8"),
        headers={"Content-Type": "application/json", "X-API-Key": api_key},
    )
    assert resp.status_code == 200
    domain_id = resp.json()["data"]["domain_id"]
    updates_after_create = _client.get("/api/v1/projects/prj_dom/updates")
    assert updates_after_create.status_code == 200
    create_item = updates_after_create.json()["data"]["items"][0]
    assert create_item["update_type"] == "domain"
    assert create_item["source_ref"] == domain_id

    # Force token to known value for verification test.
    db = _db()
    try:
        row = db.query(ProjectDomain).filter(ProjectDomain.domain_id == domain_id).first()
        assert row is not None
        row.dns_txt_token = "token_ok"
        db.commit()
    finally:
        db.close()

    # List
    resp = _client.get("/api/v1/projects/prj_dom/domains")
    assert resp.status_code == 200
    items = resp.json()["data"]["items"]
    assert len(items) == 1
    assert items[0]["domain"] == "example.com"

    # Verify
    resp = _client.post(
        f"/api/v1/agent/projects/prj_dom/domains/{domain_id}/verify",
        content=b"{}",
        headers={"Content-Type": "application/json", "X-API-Key": api_key},
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["status"] == "verified"
    updates_after_verify = _client.get("/api/v1/projects/prj_dom/updates")
    assert updates_after_verify.status_code == 200
    items = updates_after_verify.json()["data"]["items"]
    assert len(items) == 2
    assert items[0]["title"] == "Domain verified: example.com"
