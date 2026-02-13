from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

# Make `src` importable whether pytest runs from repo root or backend/.
BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from src.api.v1.dependencies import require_agent_auth
from src.core.database import Base, get_db

# Ensure tables are registered on Base.metadata
from src.models.agent import Agent  # noqa: F401
from src.models.audit_log import AuditLog  # noqa: F401


def _make_test_app(db_session_factory: sessionmaker[Session]) -> FastAPI:
    app = FastAPI()

    def _override_get_db():
        db = db_session_factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = _override_get_db

    @app.post("/agent-test")
    async def agent_test(_: object = Depends(require_agent_auth)) -> dict[str, bool]:
        return {"ok": True}

    return app


def _latest_agent_audit(db: Session) -> AuditLog | None:
    return (
        db.query(AuditLog)
        .filter(AuditLog.actor_type == "agent")
        .order_by(AuditLog.id.desc())
        .first()
    )


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


def test_agent_auth_missing_key_is_audited(_db: sessionmaker[Session]) -> None:
    app = _make_test_app(_db)
    client = TestClient(app)

    resp = client.post("/agent-test", json={"x": 1})
    assert resp.status_code == 401

    with _db() as db:
        audit = _latest_agent_audit(db)
        assert audit is not None
        assert audit.path == "/agent-test"
        assert audit.error_hint == "missing_agent_api_key"


def test_agent_auth_malformed_key_is_audited(_db: sessionmaker[Session]) -> None:
    app = _make_test_app(_db)
    client = TestClient(app)

    resp = client.post("/agent-test", headers={"X-API-Key": "not-a-valid-key"}, json={"x": 1})
    assert resp.status_code == 401

    with _db() as db:
        audit = _latest_agent_audit(db)
        assert audit is not None
        assert audit.error_hint == "invalid_agent_api_key_format"


def test_agent_auth_unknown_agent_is_audited(_db: sessionmaker[Session]) -> None:
    app = _make_test_app(_db)
    client = TestClient(app)

    resp = client.post(
        "/agent-test",
        headers={"X-API-Key": "ag_doesnotexist.secret"},
        json={"x": 1},
    )
    assert resp.status_code == 401

    with _db() as db:
        audit = _latest_agent_audit(db)
        assert audit is not None
        assert audit.agent_id == "ag_doesnotexist"
        assert audit.error_hint == "invalid_or_revoked_agent"


def test_agent_auth_wrong_secret_is_audited(_db: sessionmaker[Session]) -> None:
    # Create agent row with a known api_key_hash, then send a different secret.
    from src.core.security import generate_agent_api_key, hash_api_key

    with _db() as db:
        agent_id = "ag_testagent"
        valid_api_key = generate_agent_api_key(agent_id)
        agent = Agent(
            agent_id=agent_id,
            name="Test",
            capabilities_json="[]",
            wallet_address=None,
            api_key_hash=hash_api_key(valid_api_key),
            api_key_last4=valid_api_key[-4:],
        )
        db.add(agent)
        db.commit()

    app = _make_test_app(_db)
    client = TestClient(app)

    resp = client.post(
        "/agent-test",
        headers={"X-API-Key": f"{agent_id}.wrongsecret"},
        json={"x": 1},
    )
    assert resp.status_code == 401

    with _db() as db:
        audit = _latest_agent_audit(db)
        assert audit is not None
        assert audit.agent_id == agent_id
        assert audit.error_hint == "invalid_agent_api_key_hash"

