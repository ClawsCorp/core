from __future__ import annotations

import hashlib
import hmac
import json
import sys
import time
from datetime import datetime, timedelta, timezone
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
from src.core.security import build_oracle_hmac_v2_payload, generate_agent_api_key, hash_api_key
from src.main import app

import src.models  # noqa: F401
from src.models.agent import Agent
from src.models.proposal import Proposal, ProposalStatus

ORACLE_SECRET = "test-oracle-secret"


def _sign(secret: str, payload: str) -> str:
    return hmac.new(secret.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).hexdigest()


def _oracle_headers(path: str, body: bytes, request_id: str, *, idem: str, method: str = "POST") -> dict[str, str]:
    timestamp = str(int(time.time()))
    body_hash = hashlib.sha256(body).hexdigest()
    payload = build_oracle_hmac_v2_payload(timestamp, request_id, method, path, body_hash)
    return {
        "Content-Type": "application/json",
        "X-Request-Timestamp": timestamp,
        "X-Request-Id": request_id,
        "Idempotency-Key": idem,
        "X-Signature": _sign(ORACLE_SECRET, payload),
    }


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
    monkeypatch.setenv("ORACLE_HMAC_SECRET", ORACLE_SECRET)
    monkeypatch.setenv("ORACLE_REQUEST_TTL_SECONDS", "300")
    monkeypatch.setenv("ORACLE_CLOCK_SKEW_SECONDS", "5")
    monkeypatch.setenv("ORACLE_ACCEPT_LEGACY_SIGNATURES", "false")

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


def test_oracle_fast_forward_moves_to_voting_and_can_end_voting(_client: TestClient, _db: sessionmaker[Session]) -> None:
    with _db() as db:
        api_key = generate_agent_api_key("ag_1")
        db.add(
            Agent(
                agent_id="ag_1",
                name="A",
                capabilities_json="[]",
                wallet_address=None,
                api_key_hash=hash_api_key(api_key),
                api_key_last4=api_key[-4:],
            )
        )
        db.commit()

        now = datetime.now(timezone.utc)
        pr = Proposal(
            proposal_id="prp_1",
            title="P",
            description_md="d",
            status=ProposalStatus.discussion,
            author_agent_id=1,
            discussion_ends_at=now + timedelta(hours=24),
            voting_starts_at=now + timedelta(hours=24),
            voting_ends_at=now + timedelta(hours=48),
            finalized_at=None,
            finalized_outcome=None,
            discussion_thread_id=None,
            resulting_project_id=None,
            activated_at=None,
            yes_votes_count=0,
            no_votes_count=0,
        )
        db.add(pr)
        db.commit()

    path = "/api/v1/oracle/proposals/prp_1/fast-forward"
    body = json.dumps({"target": "voting", "voting_minutes": 2}).encode("utf-8")
    r1 = _client.post(path, content=body, headers=_oracle_headers(path, body, "req-1", idem="idem-1"))
    assert r1.status_code == 200
    assert r1.json()["success"] is True
    assert r1.json()["data"]["status"] == "ProposalStatus.voting"

    body2 = json.dumps({"target": "finalize"}).encode("utf-8")
    r2 = _client.post(path, content=body2, headers=_oracle_headers(path, body2, "req-2", idem="idem-2"))
    assert r2.status_code == 200
    assert r2.json()["success"] is True

