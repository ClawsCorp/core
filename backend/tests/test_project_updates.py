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

from src.api.v1.dependencies import require_agent_auth
from src.core.database import Base, get_db
from src.main import app

import src.models  # noqa: F401
from src.models.agent import Agent
from src.models.audit_log import AuditLog
from src.models.project import Project, ProjectStatus
from src.models.project_member import ProjectMember, ProjectMemberRole
from src.models.project_update import ProjectUpdate
from src.services.project_updates import (
    build_project_update_idempotency_key,
    create_project_update_row,
    project_update_public,
    populate_project_update_structured_refs,
)


def test_project_updates_create_and_list() -> None:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    session_local = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    Base.metadata.create_all(bind=engine)

    with session_local() as db:
        agent = Agent(
            agent_id="ag_updates_1",
            name="Updater",
            capabilities_json="[]",
            wallet_address=None,
            api_key_hash="hash",
            api_key_last4="1234",
        )
        db.add(agent)
        db.flush()
        project = Project(
            project_id="prj_updates_1",
            slug="updates-one",
            name="Updates One",
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
        db.add(
            ProjectMember(
                project_id=project.id,
                agent_id=agent.id,
                role=ProjectMemberRole.maintainer,
            )
        )
        db.commit()

    def _override_get_db():
        db: Session = session_local()
        try:
            yield db
        finally:
            db.close()

    def _override_agent_auth() -> Agent:
        with session_local() as db:
            return db.query(Agent).filter(Agent.agent_id == "ag_updates_1").one()

    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[require_agent_auth] = _override_agent_auth
    client = TestClient(app, raise_server_exceptions=False)
    try:
        create_resp = client.post(
            "/api/v1/agent/projects/prj_updates_1/updates",
            json={
                "title": "Delivery completed",
                "body_md": "Frontend and backend deliverables merged.",
                "update_type": "delivery",
                "source_kind": "delivery_receipt",
                "source_ref": "receipt:prj_updates_1",
                "ref_kind": "project_section",
                "ref_url": "/projects/prj_updates_1#delivery-receipt",
                "tx_hash": "0x" + ("ab" * 32),
                "idempotency_key": "upd:test:1",
            },
            headers={"X-Request-Id": "req-upd-1"},
        )
        assert create_resp.status_code == 200
        create_data = create_resp.json()["data"]
        assert create_data["project_id"] == "prj_updates_1"
        assert create_data["author_agent_id"] == "ag_updates_1"
        assert create_data["title"] == "Delivery completed"
        assert create_data["ref_kind"] == "project_section"
        assert create_data["ref_url"] == "/projects/prj_updates_1#delivery-receipt"
        assert create_data["tx_hash"] == "0x" + ("ab" * 32)

        second_resp = client.post(
            "/api/v1/agent/projects/prj_updates_1/updates",
            json={
                "title": "Delivery completed",
                "body_md": "Frontend and backend deliverables merged.",
                "update_type": "delivery",
                "source_kind": "delivery_receipt",
                "source_ref": "receipt:prj_updates_1",
                "ref_kind": "project_section",
                "ref_url": "/projects/prj_updates_1#delivery-receipt",
                "tx_hash": "0x" + ("ab" * 32),
                "idempotency_key": "upd:test:1",
            },
            headers={"X-Request-Id": "req-upd-2"},
        )
        assert second_resp.status_code == 200
        assert second_resp.json()["data"]["update_id"] == create_data["update_id"]

        list_resp = client.get("/api/v1/projects/prj_updates_1/updates")
        assert list_resp.status_code == 200
        payload = list_resp.json()
        assert payload["success"] is True
        assert payload["data"]["total"] == 1
        item = payload["data"]["items"][0]
        assert item["title"] == "Delivery completed"
        assert item["source_kind"] == "delivery_receipt"
        assert item["source_ref"] == "receipt:prj_updates_1"
        assert item["ref_kind"] == "project_section"
        assert item["ref_url"] == "/projects/prj_updates_1#delivery-receipt"
        assert item["tx_hash"] == "0x" + ("ab" * 32)
    finally:
        app.dependency_overrides.clear()


def test_project_update_dedupe_does_not_rollback_pending_audit() -> None:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    session_local = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    Base.metadata.create_all(bind=engine)

    with session_local() as db:
        agent = Agent(
            agent_id="ag_updates_2",
            name="Updater Two",
            capabilities_json="[]",
            wallet_address=None,
            api_key_hash="hash",
            api_key_last4="5678",
        )
        db.add(agent)
        db.flush()
        project = Project(
            project_id="prj_updates_2",
            slug="updates-two",
            name="Updates Two",
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

    with session_local() as db:
        agent = db.query(Agent).filter(Agent.agent_id == "ag_updates_2").one()
        project = db.query(Project).filter(Project.project_id == "prj_updates_2").one()
        row, created = create_project_update_row(
            db,
            project=project,
            agent=agent,
            title="First",
            body_md="Body",
            update_type="ops",
            idempotency_key="upd:test:dedupe",
        )
        assert created is True
        db.commit()
        assert row.update_id

    with session_local() as db:
        agent = db.query(Agent).filter(Agent.agent_id == "ag_updates_2").one()
        project = db.query(Project).filter(Project.project_id == "prj_updates_2").one()
        db.add(
            AuditLog(
                actor_type="agent",
                agent_id=agent.agent_id,
                method="POST",
                path="/api/v1/agent/projects/prj_updates_2/updates",
                idempotency_key="upd:test:dedupe",
                body_hash="abc123",
                signature_status="none",
                request_id="req-dedupe-audit",
            )
        )
        row, created = create_project_update_row(
            db,
            project=project,
            agent=agent,
            title="First",
            body_md="Body",
            update_type="ops",
            idempotency_key="upd:test:dedupe",
        )
        assert created is False
        db.commit()

        assert db.query(ProjectUpdate).count() == 1
        assert db.query(AuditLog).count() == 1
        assert row.update_id


def test_build_project_update_idempotency_key_caps_length() -> None:
    source = "x" * 240
    key = build_project_update_idempotency_key(
        prefix="project_update:oracle_expense",
        source_idempotency_key=source,
    )
    assert len(key) <= 255
    assert key.startswith("project_update:oracle_expense:")
    assert "sha256:" in key


def test_project_updates_api_derives_structured_refs_for_legacy_rows() -> None:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    session_local = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    Base.metadata.create_all(bind=engine)

    with session_local() as db:
        project = Project(
            project_id="prj_updates_legacy",
            slug="updates-legacy",
            name="Updates Legacy",
            description_md=None,
            status=ProjectStatus.active,
            proposal_id=None,
            origin_proposal_id=None,
            originator_agent_id=None,
            discussion_thread_id="thr_legacy",
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
        db.add(
            ProjectUpdate(
                update_id="pup_legacy_ref",
                idempotency_key="upd:test:legacy",
                project_id=project.id,
                author_agent_id=None,
                update_type="expense",
                title="Legacy payout",
                body_md="Bounty paid in tx `0x" + ("cd" * 32) + "`.",
                source_kind="bounty_paid",
                source_ref="bty_legacy",
                ref_kind=None,
                ref_url=None,
                tx_hash=None,
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
        list_resp = client.get("/api/v1/projects/prj_updates_legacy/updates")
        assert list_resp.status_code == 200
        item = list_resp.json()["data"]["items"][0]
        assert item["ref_kind"] == "bounty"
        assert item["ref_url"] == "/bounties/bty_legacy"
        assert item["tx_hash"] == "0x" + ("cd" * 32)
    finally:
        app.dependency_overrides.clear()


def test_populate_project_update_structured_refs_backfills_legacy_row() -> None:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    session_local = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    Base.metadata.create_all(bind=engine)

    with session_local() as db:
        project = Project(
            project_id="prj_updates_fill",
            slug="updates-fill",
            name="Updates Fill",
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
        row = ProjectUpdate(
            update_id="pup_fill_ref",
            idempotency_key="upd:test:fill",
            project_id=project.id,
            author_agent_id=None,
            update_type="billing",
            title="Legacy invoice",
            body_md="Settled via 0x" + ("ef" * 32),
            source_kind="billing_settlement",
            source_ref="inv_fill",
            ref_kind=None,
            ref_url=None,
            tx_hash=None,
        )
        db.add(row)
        db.commit()
        db.refresh(row)

        changed = populate_project_update_structured_refs(
            project_public_id=project.project_id,
            discussion_thread_id=project.discussion_thread_id,
            row=row,
        )
        assert changed is True
        assert row.ref_kind == "project_section"
        assert row.ref_url == "/projects/prj_updates_fill#crypto-billing"
        assert row.tx_hash == "0x" + ("ef" * 32)


def test_project_update_public_preserves_stored_ref_kind_when_only_ref_url_is_derived() -> None:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    session_local = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    Base.metadata.create_all(bind=engine)

    with session_local() as db:
        project = Project(
            project_id="prj_updates_preserve",
            slug="updates-preserve",
            name="Updates Preserve",
            description_md=None,
            status=ProjectStatus.active,
            proposal_id=None,
            origin_proposal_id=None,
            originator_agent_id=None,
            discussion_thread_id="thr_preserve",
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
        row = ProjectUpdate(
            update_id="pup_preserve_kind",
            idempotency_key="upd:test:preserve_kind",
            project_id=project.id,
            author_agent_id=None,
            update_type="ops",
            title="Stored ref kind only",
            body_md="No body",
            source_kind="manual_smoke",
            source_ref="smoke:1",
            ref_kind="custom_manual",
            ref_url=None,
            tx_hash=None,
        )
        db.add(row)
        db.commit()

        public = project_update_public(project, row, None)
        assert public["ref_kind"] == "custom_manual"
        assert public["ref_url"] == "/discussions/threads/thr_preserve"


def test_project_updates_support_server_side_commercial_and_operational_slices() -> None:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    session_local = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    Base.metadata.create_all(bind=engine)

    with session_local() as db:
        project = Project(
            project_id="prj_updates_slice",
            slug="updates-slice",
            name="Updates Slice",
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
        db.add_all(
            [
                ProjectUpdate(
                    update_id="pup_slice_1",
                    idempotency_key="upd:test:slice:1",
                    project_id=project.id,
                    author_agent_id=None,
                    update_type="revenue",
                    title="Commercial row",
                    body_md=None,
                    source_kind="billing_settlement",
                    source_ref="inv_1",
                    ref_kind=None,
                    ref_url=None,
                    tx_hash=None,
                ),
                ProjectUpdate(
                    update_id="pup_slice_2",
                    idempotency_key="upd:test:slice:2",
                    project_id=project.id,
                    author_agent_id=None,
                    update_type="funding",
                    title="Operational row",
                    body_md=None,
                    source_kind="funding_round",
                    source_ref="fr_1",
                    ref_kind=None,
                    ref_url=None,
                    tx_hash=None,
                ),
            ]
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
        commercial_resp = client.get("/api/v1/projects/prj_updates_slice/updates?slice=commercial")
        assert commercial_resp.status_code == 200
        commercial_items = commercial_resp.json()["data"]["items"]
        assert len(commercial_items) == 1
        assert commercial_items[0]["source_kind"] == "billing_settlement"

        operational_resp = client.get("/api/v1/projects/prj_updates_slice/updates?slice=operational")
        assert operational_resp.status_code == 200
        operational_items = operational_resp.json()["data"]["items"]
        assert len(operational_items) == 1
        assert operational_items[0]["source_kind"] == "funding_round"
    finally:
        app.dependency_overrides.clear()


def test_project_updates_slice_alias_endpoints_match_slice_query() -> None:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    session_local = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    Base.metadata.create_all(bind=engine)

    with session_local() as db:
        project = Project(
            project_id="prj_updates_slice_alias",
            slug="updates-slice-alias",
            name="Updates Slice Alias",
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
        db.add_all(
            [
                ProjectUpdate(
                    update_id="pup_alias_1",
                    idempotency_key="upd:test:alias:1",
                    project_id=project.id,
                    author_agent_id=None,
                    update_type="revenue",
                    title="Commercial alias row",
                    body_md=None,
                    source_kind="billing_settlement",
                    source_ref="inv_alias_1",
                    ref_kind=None,
                    ref_url=None,
                    tx_hash=None,
                ),
                ProjectUpdate(
                    update_id="pup_alias_2",
                    idempotency_key="upd:test:alias:2",
                    project_id=project.id,
                    author_agent_id=None,
                    update_type="funding",
                    title="Operational alias row",
                    body_md=None,
                    source_kind="funding_round",
                    source_ref="fr_alias_1",
                    ref_kind=None,
                    ref_url=None,
                    tx_hash=None,
                ),
            ]
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
        commercial_query = client.get("/api/v1/projects/prj_updates_slice_alias/updates?slice=commercial")
        commercial_alias = client.get("/api/v1/projects/prj_updates_slice_alias/updates/commercial")
        assert commercial_query.status_code == 200
        assert commercial_alias.status_code == 200
        assert commercial_alias.json()["data"]["items"] == commercial_query.json()["data"]["items"]

        operational_query = client.get("/api/v1/projects/prj_updates_slice_alias/updates?slice=operational")
        operational_alias = client.get("/api/v1/projects/prj_updates_slice_alias/updates/operational")
        assert operational_query.status_code == 200
        assert operational_alias.status_code == 200
        assert operational_alias.json()["data"]["items"] == operational_query.json()["data"]["items"]
    finally:
        app.dependency_overrides.clear()


def test_project_updates_latest_endpoint_returns_newest_item_or_null() -> None:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    session_local = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    Base.metadata.create_all(bind=engine)

    with session_local() as db:
        project = Project(
            project_id="prj_updates_latest",
            slug="updates-latest",
            name="Updates Latest",
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

    def _override_get_db():
        db: Session = session_local()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = _override_get_db
    client = TestClient(app, raise_server_exceptions=False)
    try:
        empty_resp = client.get("/api/v1/projects/prj_updates_latest/updates/latest")
        assert empty_resp.status_code == 200
        assert empty_resp.json()["data"] is None

        with session_local() as db:
            project = db.query(Project).filter(Project.project_id == "prj_updates_latest").one()
            db.add(
                ProjectUpdate(
                    update_id="pup_latest_1",
                    idempotency_key="upd:test:latest:1",
                    project_id=project.id,
                    author_agent_id=None,
                    update_type="ops",
                    title="Older",
                    body_md=None,
                    source_kind="funding_round",
                    source_ref="fr_1",
                    ref_kind=None,
                    ref_url=None,
                    tx_hash=None,
                )
            )
            db.add(
                ProjectUpdate(
                    update_id="pup_latest_2",
                    idempotency_key="upd:test:latest:2",
                    project_id=project.id,
                    author_agent_id=None,
                    update_type="revenue",
                    title="Newest",
                    body_md=None,
                    source_kind="billing_settlement",
                    source_ref="inv_2",
                    ref_kind=None,
                    ref_url=None,
                    tx_hash=None,
                )
            )
            db.commit()

        latest_resp = client.get("/api/v1/projects/prj_updates_latest/updates/latest")
        assert latest_resp.status_code == 200
        payload = latest_resp.json()
        assert payload["data"]["title"] == "Newest"
        assert payload["data"]["source_kind"] == "billing_settlement"
    finally:
        app.dependency_overrides.clear()


def test_project_updates_summary_returns_counts_and_latest_by_slice() -> None:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    session_local = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    Base.metadata.create_all(bind=engine)

    with session_local() as db:
        project = Project(
            project_id="prj_updates_summary",
            slug="updates-summary",
            name="Updates Summary",
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
        db.add_all(
            [
                ProjectUpdate(
                    update_id="pup_sum_1",
                    idempotency_key="upd:test:sum:1",
                    project_id=project.id,
                    author_agent_id=None,
                    update_type="funding",
                    title="Operational summary item",
                    body_md=None,
                    source_kind="funding_round",
                    source_ref="fr_1",
                    ref_kind=None,
                    ref_url=None,
                    tx_hash=None,
                ),
                ProjectUpdate(
                    update_id="pup_sum_2",
                    idempotency_key="upd:test:sum:2",
                    project_id=project.id,
                    author_agent_id=None,
                    update_type="revenue",
                    title="Commercial summary item",
                    body_md=None,
                    source_kind="billing_settlement",
                    source_ref="inv_1",
                    ref_kind=None,
                    ref_url=None,
                    tx_hash=None,
                ),
            ]
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
        resp = client.get("/api/v1/projects/prj_updates_summary/updates/summary")
        assert resp.status_code == 200
        assert resp.headers["Cache-Control"] == "public, max-age=30"
        assert "project-updates-summary:prj_updates_summary:2:1:1:" in resp.headers["ETag"]
        data = resp.json()["data"]
        assert data["project_id"] == "prj_updates_summary"
        assert data["total_count"] == 2
        assert data["commercial_count"] == 1
        assert data["operational_count"] == 1
        assert data["latest"]["title"] == "Commercial summary item"
        assert data["latest_commercial"]["title"] == "Commercial summary item"
        assert data["latest_operational"]["title"] == "Operational summary item"

        cached_resp = client.get(
            "/api/v1/projects/prj_updates_summary/updates/summary",
            headers={"If-None-Match": resp.headers["ETag"]},
        )
        assert cached_resp.status_code == 304
        assert cached_resp.headers["Cache-Control"] == "public, max-age=30"
        assert cached_resp.headers["ETag"] == resp.headers["ETag"]
    finally:
        app.dependency_overrides.clear()


def test_project_updates_source_kinds_summary_groups_counts_and_latest() -> None:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    session_local = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    Base.metadata.create_all(bind=engine)

    with session_local() as db:
        agent = Agent(
            agent_id="ag_updates_kind_1",
            name="Kinds Bot",
            capabilities_json="[]",
            wallet_address=None,
            api_key_hash="hash",
            api_key_last4="3141",
        )
        db.add(agent)
        db.flush()
        project = Project(
            project_id="prj_updates_kinds",
            slug="updates-kinds",
            name="Updates Kinds",
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
        db.add_all(
            [
                ProjectUpdate(
                    update_id="pup_kind_1",
                    idempotency_key="upd:test:kind:1",
                    project_id=project.id,
                    author_agent_id=agent.id,
                    update_type="revenue",
                    title="Invoice opened",
                    body_md=None,
                    source_kind="crypto_invoice",
                    source_ref="inv_1",
                    ref_kind=None,
                    ref_url=None,
                    tx_hash=None,
                ),
                ProjectUpdate(
                    update_id="pup_kind_2",
                    idempotency_key="upd:test:kind:2",
                    project_id=project.id,
                    author_agent_id=None,
                    update_type="revenue",
                    title="Invoice settled",
                    body_md=None,
                    source_kind="crypto_invoice",
                    source_ref="inv_1",
                    ref_kind=None,
                    ref_url=None,
                    tx_hash=None,
                ),
                ProjectUpdate(
                    update_id="pup_kind_3",
                    idempotency_key="upd:test:kind:3",
                    project_id=project.id,
                    author_agent_id=None,
                    update_type="ops",
                    title="Manual ops note",
                    body_md=None,
                    source_kind=None,
                    source_ref=None,
                    ref_kind=None,
                    ref_url=None,
                    tx_hash=None,
                ),
            ]
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
        resp = client.get("/api/v1/projects/prj_updates_kinds/updates/source-kinds")
        assert resp.status_code == 200
        payload = resp.json()
        assert payload["success"] is True
        assert payload["data"]["project_id"] == "prj_updates_kinds"
        assert payload["data"]["total_count"] == 3
        buckets = payload["data"]["buckets"]
        assert len(buckets) == 2
        assert buckets[0]["source_kind"] == "crypto_invoice"
        assert buckets[0]["count"] == 2
        assert buckets[0]["latest"]["title"] == "Invoice settled"
        assert buckets[1]["source_kind"] is None
        assert buckets[1]["count"] == 1
        assert buckets[1]["latest"]["title"] == "Manual ops note"
    finally:
        app.dependency_overrides.clear()
