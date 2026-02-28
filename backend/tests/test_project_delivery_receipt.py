from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

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
from src.models.bounty import Bounty, BountyFundingSource, BountyStatus
from src.models.git_outbox import GitOutbox
from src.models.project import Project, ProjectStatus


def test_project_delivery_receipt_returns_ready_snapshot() -> None:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    session_local = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    Base.metadata.create_all(bind=engine)

    with session_local() as db:
        project = Project(
            project_id="proj_receipt_1",
            slug="receipt-one",
            name="Receipt One",
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
        bounty = Bounty(
            bounty_id="bty_receipt_1",
            idempotency_key="bty:receipt:1",
            project_id=project.id,
            origin_proposal_id="prp_receipt_1",
            origin_milestone_id=None,
            funding_source=BountyFundingSource.project_capital,
            title="Backend artifact",
            description_md=None,
            amount_micro_usdc=500_000,
            priority=None,
            deadline_at=None,
            status=BountyStatus.paid,
            claimant_agent_id=None,
            claimed_at=None,
            submitted_at=datetime.now(timezone.utc),
            pr_url="https://github.com/ClawsCorp/core/pull/244",
            merge_sha="d9f6aab5688b2c0ff0c8d7405ceaf1e1fa236a15",
            paid_tx_hash="0xpaid",
        )
        db.add(bounty)
        db.flush()
        db.add(
            GitOutbox(
                task_id="gto_receipt_1",
                idempotency_key="git:receipt:1",
                project_id=project.id,
                requested_by_agent_id=None,
                task_type="create_project_backend_artifact_commit",
                payload_json='{"slug":"receipt-one","bounty_id":"bty_receipt_1"}',
                result_json='{"pr_url":"https://github.com/ClawsCorp/core/pull/244"}',
                branch_name="codex/receipt-one",
                commit_sha="a3dd2a99a060a0762cae3238c02e891e39a8c7c3",
                status="failed",
                attempts=1,
                last_error_hint="auto merge not enabled",
                locked_at=None,
                locked_by=None,
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
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
        resp = client.get("/api/v1/projects/proj_receipt_1/delivery-receipt")
        assert resp.status_code == 200
        payload = resp.json()
        assert payload["success"] is True
        data = payload["data"]
        assert data["project_id"] == "proj_receipt_1"
        assert data["status"] == "ready"
        assert data["items_total"] == 1
        assert data["items_ready"] == 1
        item = data["items"][0]
        assert item["bounty_id"] == "bty_receipt_1"
        assert item["git_task_id"] == "gto_receipt_1"
        assert item["git_task_status"] == "failed"
        assert item["git_source_commit_sha"] == "a3dd2a99a060a0762cae3238c02e891e39a8c7c3"
        assert item["git_accepted_merge_sha"] == "d9f6aab5688b2c0ff0c8d7405ceaf1e1fa236a15"
        assert item["git_pr_url"] == "https://github.com/ClawsCorp/core/pull/244"
    finally:
        app.dependency_overrides.clear()
