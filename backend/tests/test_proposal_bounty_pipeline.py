from __future__ import annotations

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

from src.core.database import Base, get_db
from src.main import app

import src.models  # noqa: F401
from src.models.agent import Agent
from src.models.bounty import Bounty, BountyFundingSource, BountyStatus
from src.models.proposal import Proposal, ProposalStatus


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


def test_proposal_detail_includes_related_bounties_and_list_filter_works(
    _client: TestClient, _db: sessionmaker[Session]
) -> None:
    with _db() as db:
        agent = Agent(
            agent_id="agt_1",
            name="A1",
            api_key_hash="x",
            api_key_last4="0000",
            wallet_address=None,
            capabilities_json="{}",
        )
        db.add(agent)
        db.commit()
        db.refresh(agent)

        proposal = Proposal(
            proposal_id="prp_1",
            title="P1",
            description_md="d",
            status=ProposalStatus.discussion,
            author_agent_id=agent.id,
            discussion_ends_at=datetime(2026, 2, 15, 0, 0, 0, tzinfo=timezone.utc),
            voting_starts_at=datetime(2026, 2, 15, 0, 0, 0, tzinfo=timezone.utc),
            voting_ends_at=datetime(2026, 2, 16, 0, 0, 0, tzinfo=timezone.utc),
            finalized_at=None,
            finalized_outcome=None,
            discussion_thread_id=None,
            resulting_project_id=None,
            activated_at=None,
            yes_votes_count=0,
            no_votes_count=0,
        )
        db.add(proposal)
        db.commit()

        bounty = Bounty(
            bounty_id="bty_1",
            idempotency_key=None,
            project_id=None,
            origin_proposal_id="prp_1",
            funding_source=BountyFundingSource.platform_treasury,
            title="B1",
            description_md=None,
            amount_micro_usdc=123,
            priority="high",
            deadline_at=datetime(2026, 2, 20, 0, 0, 0, tzinfo=timezone.utc),
            status=BountyStatus.open,
            claimant_agent_id=None,
            claimed_at=None,
            submitted_at=None,
            pr_url=None,
            merge_sha=None,
            paid_tx_hash=None,
        )
        db.add(bounty)
        db.commit()

    r = _client.get("/api/v1/proposals/prp_1")
    assert r.status_code == 200
    body = r.json()
    assert body["success"] is True
    assert body["data"]["proposal_id"] == "prp_1"
    assert len(body["data"]["related_bounties"]) == 1
    assert body["data"]["related_bounties"][0]["bounty_id"] == "bty_1"
    assert body["data"]["related_bounties"][0]["origin_proposal_id"] == "prp_1"

    r2 = _client.get("/api/v1/bounties?origin_proposal_id=prp_1")
    assert r2.status_code == 200
    items = r2.json()["data"]["items"]
    assert len(items) == 1
    assert items[0]["bounty_id"] == "bty_1"
