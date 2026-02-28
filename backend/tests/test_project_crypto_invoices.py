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


def _register_agent(_client: TestClient, name: str) -> str:
    resp = _client.post(
        "/api/v1/agents/register",
        json={
            "name": name,
            "capabilities": ["billing"],
            "wallet_address": "0x00000000000000000000000000000000000000aa",
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    return str(body["api_key"])


def test_project_crypto_invoice_create_and_list_support_numeric_and_public_ids(
    _client: TestClient, _db: sessionmaker[Session]
) -> None:
    with _db() as db:
        project = Project(
            project_id="prj_crypto",
            slug="crypto",
            name="Crypto Project",
            description_md=None,
            status=ProjectStatus.active,
            proposal_id=None,
            origin_proposal_id=None,
            originator_agent_id=None,
            discussion_thread_id=None,
            treasury_wallet_address=None,
            treasury_address=None,
            revenue_wallet_address=None,
            revenue_address="0x00000000000000000000000000000000000000bb",
            monthly_budget_micro_usdc=None,
            created_by_agent_id=None,
            approved_at=None,
        )
        db.add(project)
        db.commit()
        project_num = int(project.id)

    api_key = _register_agent(_client, "Invoice Agent")

    create_resp = _client.post(
        f"/api/v1/agent/projects/{project_num}/crypto-invoices",
        headers={"X-API-Key": api_key, "Content-Type": "application/json"},
        json={
            "amount_micro_usdc": 123456,
            "payer_address": "0x00000000000000000000000000000000000000cc",
            "description": "Demo invoice",
            "chain_id": 84532,
        },
    )
    assert create_resp.status_code == 200
    created = create_resp.json()["data"]
    assert created["project_num"] == project_num
    assert created["project_id"] == "prj_crypto"
    assert created["status"] == "pending"
    assert created["payment_address"] == "0x00000000000000000000000000000000000000bb"
    updates_resp = _client.get("/api/v1/projects/prj_crypto/updates")
    assert updates_resp.status_code == 200
    updates = updates_resp.json()["data"]["items"]
    assert len(updates) == 1
    assert updates[0]["update_type"] == "billing"
    assert updates[0]["source_ref"] == created["invoice_id"]

    list_public = _client.get("/api/v1/projects/prj_crypto/crypto-invoices")
    assert list_public.status_code == 200
    items_public = list_public.json()["data"]["items"]
    assert len(items_public) == 1

    list_numeric = _client.get(f"/api/v1/projects/{project_num}/crypto-invoices")
    assert list_numeric.status_code == 200
    items_numeric = list_numeric.json()["data"]["items"]
    assert len(items_numeric) == 1
    assert items_numeric[0]["invoice_id"] == created["invoice_id"]


def test_project_crypto_invoice_create_fail_closed_without_revenue_address(
    _client: TestClient, _db: sessionmaker[Session]
) -> None:
    with _db() as db:
        project = Project(
            project_id="prj_no_rev",
            slug="no-rev",
            name="No Revenue",
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
        db.commit()

    api_key = _register_agent(_client, "No Revenue Agent")

    create_resp = _client.post(
        "/api/v1/agent/projects/prj_no_rev/crypto-invoices",
        headers={"X-API-Key": api_key, "Content-Type": "application/json"},
        json={"amount_micro_usdc": 1000},
    )
    assert create_resp.status_code == 400
    assert "project_revenue_address_missing" in create_resp.text
