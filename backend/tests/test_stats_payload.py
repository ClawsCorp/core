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


def test_stats_includes_project_capital_reconciliation_max_age_seconds(
    _client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PROJECT_CAPITAL_RECONCILIATION_MAX_AGE_SECONDS", "3600")
    get_settings.cache_clear()

    r1 = _client.get("/api/v1/stats")
    assert r1.status_code == 200
    payload1 = r1.json()
    assert payload1["success"] is True
    assert payload1["data"]["project_capital_reconciliation_max_age_seconds"] == 3600
    etag1 = r1.headers.get("ETag")
    assert etag1 is not None

    monkeypatch.setenv("PROJECT_CAPITAL_RECONCILIATION_MAX_AGE_SECONDS", "7200")
    get_settings.cache_clear()

    r2 = _client.get("/api/v1/stats")
    assert r2.status_code == 200
    payload2 = r2.json()
    assert payload2["data"]["project_capital_reconciliation_max_age_seconds"] == 7200
    etag2 = r2.headers.get("ETag")
    assert etag2 is not None
    assert etag2 != etag1

