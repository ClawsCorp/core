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
def _client(_db: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("DISCUSSIONS_CREATE_THREAD_MAX_PER_MINUTE", "2")

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
    agent_id = "ag_disc_rl"
    api_key = generate_agent_api_key(agent_id)
    db.add(
        Agent(
            agent_id=agent_id,
            name="DiscRateLimit",
            capabilities_json="[]",
            wallet_address=None,
            api_key_hash=hash_api_key(api_key),
            api_key_last4=api_key[-4:],
        )
    )
    db.commit()
    return api_key


def test_discussion_thread_create_rate_limited(_client: TestClient, _db: sessionmaker[Session]) -> None:
    with _db() as db:
        api_key = _seed_agent(db)

    payload = {"scope": "global", "project_id": None, "title": "Hello"}
    resp = _client.post("/api/v1/agent/discussions/threads", headers={"X-API-Key": api_key}, json=payload)
    assert resp.status_code == 200
    resp = _client.post("/api/v1/agent/discussions/threads", headers={"X-API-Key": api_key}, json=payload)
    assert resp.status_code == 200

    # Third within the same minute is blocked.
    resp = _client.post("/api/v1/agent/discussions/threads", headers={"X-API-Key": api_key}, json=payload)
    assert resp.status_code == 429
