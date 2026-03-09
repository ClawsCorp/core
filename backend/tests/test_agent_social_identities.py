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

from src.core.database import Base, get_db
from src.core.security import generate_agent_api_key, hash_api_key
from src.main import app

import src.models  # noqa: F401
from src.models.agent import Agent
from src.models.agent_social_identity import AgentSocialIdentity


def test_agent_social_identity_create_revoke_and_public_read() -> None:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    session_local = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    Base.metadata.create_all(bind=engine)

    with session_local() as db:
        agent_id = "ag_social_owner"
        api_key = generate_agent_api_key(agent_id)
        db.add(
            Agent(
                agent_id=agent_id,
                name="Social Owner",
                capabilities_json="[]",
                wallet_address=None,
                api_key_hash=hash_api_key(api_key),
                api_key_last4=api_key[-4:],
            )
        )
        db.commit()

    def _override_get_db():
        db: Session = session_local()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = _override_get_db
    client = TestClient(app, raise_server_exceptions=False)
    try:
        create_resp = client.post(
            "/api/v1/agent/social-identities",
            headers={"X-API-Key": api_key},
            json={"platform": "telegram", "handle": "@clawstelegram"},
        )
        assert create_resp.status_code == 200
        payload = create_resp.json()["data"]
        assert payload["platform"] == "telegram"
        assert payload["handle"] == "clawstelegram"

        public_resp = client.get("/api/v1/agents/ag_social_owner/social-identities")
        assert public_resp.status_code == 200
        public_items = public_resp.json()["data"]["items"]
        assert len(public_items) == 1
        assert public_items[0]["handle"] == "clawstelegram"

        revoke_resp = client.post(
            f"/api/v1/agent/social-identities/{payload['identity_id']}/revoke",
            headers={"X-API-Key": api_key},
        )
        assert revoke_resp.status_code == 200
        assert revoke_resp.json()["data"]["status"] == "revoked"

        public_resp_after = client.get("/api/v1/agents/ag_social_owner/social-identities")
        assert public_resp_after.status_code == 200
        assert public_resp_after.json()["data"]["items"] == []

        with session_local() as db:
            assert db.query(AgentSocialIdentity).count() == 1
    finally:
        app.dependency_overrides.clear()
