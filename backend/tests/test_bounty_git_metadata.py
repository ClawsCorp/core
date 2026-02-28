from __future__ import annotations

import json
import sys
from pathlib import Path

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
from src.models.bounty import Bounty, BountyFundingSource, BountyStatus
from src.models.git_outbox import GitOutbox
from src.models.project import Project, ProjectStatus
from src.services.bounty_git import (
    apply_bounty_git_metadata_backfill,
    extract_git_pr_url,
    find_backfill_git_outbox_candidate,
)


def setup_function() -> None:
    get_settings.cache_clear()


def teardown_function() -> None:
    get_settings.cache_clear()


def _make_client() -> tuple[TestClient, sessionmaker[Session]]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    session_local = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    Base.metadata.create_all(bind=engine)

    def _override_get_db():
        db = session_local()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = _override_get_db
    return TestClient(app, raise_server_exceptions=False), session_local


def test_bounty_detail_and_list_include_git_metadata() -> None:
    client, session_local = _make_client()
    try:
        with session_local() as db:
            project = Project(
                project_id="proj_git_meta_1",
                slug="git-meta-1",
                name="Git Meta Project",
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
                bounty_id="bty_git_meta_1",
                idempotency_key=None,
                project_id=project.id,
                origin_proposal_id=None,
                origin_milestone_id=None,
                funding_source=BountyFundingSource.project_capital,
                title="Git metadata bounty",
                description_md=None,
                amount_micro_usdc=1000,
                priority=None,
                deadline_at=None,
                status=BountyStatus.submitted,
                claimant_agent_id=None,
                claimed_at=None,
                submitted_at=None,
                pr_url="https://github.com/ClawsCorp/core/pull/999",
                merge_sha="abc123deadbeef",
                paid_tx_hash=None,
            )
            db.add(bounty)
            db.flush()

            db.add(
                GitOutbox(
                    task_id="gto_meta_1",
                    idempotency_key="git_meta_1",
                    project_id=project.id,
                    requested_by_agent_id=None,
                    task_type="create_project_backend_artifact_commit",
                    payload_json="{}",
                    result_json=json.dumps({"pr_url": "https://github.com/ClawsCorp/core/pull/999"}),
                    branch_name="codex/git-meta",
                    commit_sha="abc123deadbeef",
                    status="succeeded",
                    attempts=1,
                    last_error_hint=None,
                    locked_at=None,
                    locked_by=None,
                )
            )
            db.commit()

        detail = client.get("/api/v1/bounties/bty_git_meta_1")
        assert detail.status_code == 200
        body = detail.json()["data"]
        assert body["git_task_id"] == "gto_meta_1"
        assert body["git_task_type"] == "create_project_backend_artifact_commit"
        assert body["git_task_status"] == "succeeded"
        assert body["git_branch_name"] == "codex/git-meta"
        assert body["git_commit_sha"] == "abc123deadbeef"
        assert body["git_pr_url"] == "https://github.com/ClawsCorp/core/pull/999"

        listed = client.get("/api/v1/bounties?project_id=proj_git_meta_1")
        assert listed.status_code == 200
        item = listed.json()["data"]["items"][0]
        assert item["git_task_id"] == "gto_meta_1"
        assert item["git_pr_url"] == "https://github.com/ClawsCorp/core/pull/999"
    finally:
        app.dependency_overrides.clear()
        client.close()


def test_legacy_bounty_git_metadata_backfill_picks_latest_task_by_inferred_type() -> None:
    client, session_local = _make_client()
    try:
        with session_local() as db:
            project = Project(
                project_id="proj_git_meta_legacy_1",
                slug="git-meta-legacy-1",
                name="Legacy Git Meta Project",
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
                bounty_id="bty_git_meta_legacy_1",
                idempotency_key=None,
                project_id=project.id,
                origin_proposal_id=None,
                origin_milestone_id=None,
                funding_source=BountyFundingSource.project_capital,
                title="Backend API artifact",
                description_md="Legacy placeholder proof that needs a backfill.",
                amount_micro_usdc=1000,
                priority=None,
                deadline_at=None,
                status=BountyStatus.submitted,
                claimant_agent_id=None,
                claimed_at=None,
                submitted_at=None,
                pr_url="https://example.invalid/pr/bty_git_meta_legacy_1",
                merge_sha="deadbeef",
                paid_tx_hash=None,
            )
            db.add(bounty)
            db.flush()

            db.add(
                GitOutbox(
                    task_id="gto_legacy_frontend",
                    idempotency_key="git_meta_legacy_frontend",
                    project_id=project.id,
                    requested_by_agent_id=None,
                    task_type="create_app_surface_commit",
                    payload_json="{}",
                    result_json=json.dumps({"pr_url": "https://github.com/ClawsCorp/core/pull/1200"}),
                    branch_name="codex/legacy-frontend",
                    commit_sha="front123",
                    status="succeeded",
                    attempts=1,
                    last_error_hint=None,
                    locked_at=None,
                    locked_by=None,
                )
            )
            db.add(
                GitOutbox(
                    task_id="gto_legacy_backend",
                    idempotency_key="git_meta_legacy_backend",
                    project_id=project.id,
                    requested_by_agent_id=None,
                    task_type="create_project_backend_artifact_commit",
                    payload_json="{}",
                    result_json=json.dumps({"pr_url": "https://github.com/ClawsCorp/core/pull/1201"}),
                    branch_name="codex/legacy-backend",
                    commit_sha="back123",
                    status="succeeded",
                    attempts=1,
                    last_error_hint=None,
                    locked_at=None,
                    locked_by=None,
                )
            )
            db.commit()

        with session_local() as db:
            bounty = db.query(Bounty).filter(Bounty.bounty_id == "bty_git_meta_legacy_1").first()
            assert bounty is not None
            candidate = find_backfill_git_outbox_candidate(db, bounty)
            assert candidate is not None
            assert candidate.task_id == "gto_legacy_backend"
            assert extract_git_pr_url(candidate) == "https://github.com/ClawsCorp/core/pull/1201"

            changed = apply_bounty_git_metadata_backfill(bounty, candidate)
            assert changed is True
            db.commit()

        detail = client.get("/api/v1/bounties/bty_git_meta_legacy_1")
        assert detail.status_code == 200
        body = detail.json()["data"]
        assert body["pr_url"] == "https://github.com/ClawsCorp/core/pull/1201"
        assert body["merge_sha"] == "back123"
        assert body["git_task_id"] == "gto_legacy_backend"
    finally:
        app.dependency_overrides.clear()
        client.close()


def test_bounty_git_metadata_prefers_explicit_bounty_link_over_heuristic() -> None:
    client, session_local = _make_client()
    try:
        with session_local() as db:
            project = Project(
                project_id="proj_git_meta_explicit_1",
                slug="git-meta-explicit-1",
                name="Explicit Link Project",
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
                bounty_id="bty_git_meta_explicit_1",
                idempotency_key=None,
                project_id=project.id,
                origin_proposal_id=None,
                origin_milestone_id=None,
                funding_source=BountyFundingSource.project_capital,
                title="Frontend surface deliverable",
                description_md="Should match by payload bounty_id, not by title heuristic.",
                amount_micro_usdc=1000,
                priority=None,
                deadline_at=None,
                status=BountyStatus.submitted,
                claimant_agent_id=None,
                claimed_at=None,
                submitted_at=None,
                pr_url="https://example.invalid/pr/bty_git_meta_explicit_1",
                merge_sha="deadbeef",
                paid_tx_hash=None,
            )
            db.add(bounty)
            db.flush()

            db.add(
                GitOutbox(
                    task_id="gto_explicit_wrong",
                    idempotency_key="git_meta_explicit_wrong",
                    project_id=project.id,
                    requested_by_agent_id=None,
                    task_type="create_app_surface_commit",
                    payload_json="{}",
                    result_json=json.dumps({"pr_url": "https://github.com/ClawsCorp/core/pull/1300"}),
                    branch_name="codex/explicit-wrong",
                    commit_sha="wrong123",
                    status="succeeded",
                    attempts=1,
                    last_error_hint=None,
                    locked_at=None,
                    locked_by=None,
                )
            )
            db.add(
                GitOutbox(
                    task_id="gto_explicit_right",
                    idempotency_key="git_meta_explicit_right",
                    project_id=project.id,
                    requested_by_agent_id=None,
                    task_type="create_project_backend_artifact_commit",
                    payload_json=json.dumps({"bounty_id": "bty_git_meta_explicit_1"}),
                    result_json=json.dumps({"pr_url": "https://github.com/ClawsCorp/core/pull/1301"}),
                    branch_name="codex/explicit-right",
                    commit_sha="right123",
                    status="succeeded",
                    attempts=1,
                    last_error_hint=None,
                    locked_at=None,
                    locked_by=None,
                )
            )
            db.commit()

        detail = client.get("/api/v1/bounties/bty_git_meta_explicit_1")
        assert detail.status_code == 200
        body = detail.json()["data"]
        assert body["git_task_id"] == "gto_explicit_right"
        assert body["git_task_type"] == "create_project_backend_artifact_commit"
        assert body["git_pr_url"] == "https://github.com/ClawsCorp/core/pull/1301"
    finally:
        app.dependency_overrides.clear()
        client.close()
