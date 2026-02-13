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
from src.models.dividend_payout import DividendPayout
from src.models.project import Project, ProjectStatus
from src.models.project_capital_reconciliation_report import ProjectCapitalReconciliationReport
from src.models.reconciliation_report import ReconciliationReport
from src.models.settlement import Settlement


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


def test_project_detail_etag_changes_when_capital_reconciliation_changes(
    _client: TestClient, _db: sessionmaker[Session]
) -> None:
    with _db() as db:
        project = Project(
            project_id="proj_etag_1",
            slug="etag-proj",
            name="ETag Project",
            status=ProjectStatus.active,
        )
        db.add(project)
        db.commit()

    r1 = _client.get("/api/v1/projects/proj_etag_1")
    assert r1.status_code == 200
    etag1 = r1.headers.get("ETag")
    assert etag1 is not None

    with _db() as db:
        project = db.query(Project).filter(Project.project_id == "proj_etag_1").first()
        assert project is not None
        db.add(
            ProjectCapitalReconciliationReport(
                project_id=project.id,
                treasury_address="0x" + "1" * 40,
                ledger_balance_micro_usdc=0,
                onchain_balance_micro_usdc=0,
                delta_micro_usdc=0,
                ready=True,
                blocked_reason=None,
                computed_at=datetime(2026, 2, 13, 0, 0, 0, tzinfo=timezone.utc),
            )
        )
        db.commit()

    r2 = _client.get("/api/v1/projects/proj_etag_1")
    assert r2.status_code == 200
    etag2 = r2.headers.get("ETag")
    assert etag2 is not None
    assert etag2 != etag1


def test_settlement_detail_etag_changes_when_reconciliation_changes(
    _client: TestClient, _db: sessionmaker[Session]
) -> None:
    with _db() as db:
        db.add(
            Settlement(
                profit_month_id="202602",
                revenue_sum_micro_usdc=10,
                expense_sum_micro_usdc=3,
                profit_sum_micro_usdc=7,
                profit_nonnegative=True,
                note=None,
                computed_at=datetime(2026, 2, 1, 0, 0, 0, tzinfo=timezone.utc),
            )
        )
        db.add(
            ReconciliationReport(
                profit_month_id="202602",
                revenue_sum_micro_usdc=10,
                expense_sum_micro_usdc=3,
                profit_sum_micro_usdc=7,
                distributor_balance_micro_usdc=7,
                delta_micro_usdc=0,
                ready=True,
                blocked_reason=None,
                rpc_chain_id=None,
                rpc_url_name=None,
                computed_at=datetime(2026, 2, 1, 0, 1, 0, tzinfo=timezone.utc),
            )
        )
        db.commit()

    r1 = _client.get("/api/v1/settlement/202602")
    assert r1.status_code == 200
    etag1 = r1.headers.get("ETag")
    assert etag1 is not None

    with _db() as db:
        db.add(
            ReconciliationReport(
                profit_month_id="202602",
                revenue_sum_micro_usdc=10,
                expense_sum_micro_usdc=3,
                profit_sum_micro_usdc=7,
                distributor_balance_micro_usdc=6,
                delta_micro_usdc=-1,
                ready=False,
                blocked_reason="balance_mismatch",
                rpc_chain_id=None,
                rpc_url_name=None,
                computed_at=datetime(2026, 2, 1, 0, 2, 0, tzinfo=timezone.utc),
            )
        )
        db.commit()

    r2 = _client.get("/api/v1/settlement/202602")
    assert r2.status_code == 200
    etag2 = r2.headers.get("ETag")
    assert etag2 is not None
    assert etag2 != etag1


def test_settlement_months_etag_changes_when_payout_status_changes(
    _client: TestClient, _db: sessionmaker[Session]
) -> None:
    with _db() as db:
        db.add(
            Settlement(
                profit_month_id="202602",
                revenue_sum_micro_usdc=10,
                expense_sum_micro_usdc=3,
                profit_sum_micro_usdc=7,
                profit_nonnegative=True,
                note=None,
                computed_at=datetime(2026, 2, 1, 0, 0, 0, tzinfo=timezone.utc),
            )
        )
        db.add(
            ReconciliationReport(
                profit_month_id="202602",
                revenue_sum_micro_usdc=10,
                expense_sum_micro_usdc=3,
                profit_sum_micro_usdc=7,
                distributor_balance_micro_usdc=7,
                delta_micro_usdc=0,
                ready=True,
                blocked_reason=None,
                rpc_chain_id=None,
                rpc_url_name=None,
                computed_at=datetime(2026, 2, 1, 0, 1, 0, tzinfo=timezone.utc),
            )
        )
        db.add(
            DividendPayout(
                profit_month_id="202602",
                idempotency_key="payout:202602",
                status="pending",
                tx_hash="0x" + "a" * 64,
                stakers_count=1,
                authors_count=1,
                total_stakers_micro_usdc=1,
                total_treasury_micro_usdc=0,
                total_authors_micro_usdc=1,
                total_founder_micro_usdc=0,
                total_payout_micro_usdc=2,
                payout_executed_at=datetime(2026, 2, 1, 0, 3, 0, tzinfo=timezone.utc),
                confirmed_at=None,
                failed_at=None,
                block_number=None,
                created_at=datetime(2026, 2, 1, 0, 3, 1, tzinfo=timezone.utc),
            )
        )
        db.commit()

    r1 = _client.get("/api/v1/settlement/months?limit=24&offset=0")
    assert r1.status_code == 200
    etag1 = r1.headers.get("ETag")
    assert etag1 is not None

    with _db() as db:
        payout = db.query(DividendPayout).filter(DividendPayout.profit_month_id == "202602").first()
        assert payout is not None
        payout.status = "confirmed"
        payout.confirmed_at = datetime(2026, 2, 1, 0, 4, 0, tzinfo=timezone.utc)
        db.commit()

    r2 = _client.get("/api/v1/settlement/months?limit=24&offset=0")
    assert r2.status_code == 200
    etag2 = r2.headers.get("ETag")
    assert etag2 is not None
    assert etag2 != etag1

