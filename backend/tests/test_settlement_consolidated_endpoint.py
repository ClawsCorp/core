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
from src.models.project import Project, ProjectStatus
from src.models.project_settlement import ProjectSettlement
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


def test_consolidated_settlement_includes_latest_project_settlements(_client: TestClient, _db: sessionmaker[Session]) -> None:
    with _db() as db:
        p1 = Project(project_id="proj_1", slug="p1", name="P1", status=ProjectStatus.active)
        p2 = Project(project_id="proj_2", slug="p2", name="P2", status=ProjectStatus.active)
        db.add_all([p1, p2])
        db.commit()

        # Platform settlement bits.
        db.add(
            Settlement(
                profit_month_id="202602",
                revenue_sum_micro_usdc=100,
                expense_sum_micro_usdc=30,
                profit_sum_micro_usdc=70,
                profit_nonnegative=True,
                note=None,
                computed_at=datetime(2026, 2, 1, 0, 0, 0, tzinfo=timezone.utc),
            )
        )
        db.add(
            ReconciliationReport(
                profit_month_id="202602",
                revenue_sum_micro_usdc=100,
                expense_sum_micro_usdc=30,
                profit_sum_micro_usdc=70,
                distributor_balance_micro_usdc=70,
                delta_micro_usdc=0,
                ready=True,
                blocked_reason=None,
                rpc_chain_id=None,
                rpc_url_name=None,
                computed_at=datetime(2026, 2, 1, 0, 1, 0, tzinfo=timezone.utc),
            )
        )

        # Append-only project settlements; consolidated endpoint should pick latest per project.
        db.add(
            ProjectSettlement(
                project_id=p1.id,
                profit_month_id="202602",
                revenue_sum_micro_usdc=10,
                expense_sum_micro_usdc=2,
                profit_sum_micro_usdc=8,
                profit_nonnegative=True,
                note=None,
                computed_at=datetime(2026, 2, 1, 0, 0, 0, tzinfo=timezone.utc),
            )
        )
        db.add(
            ProjectSettlement(
                project_id=p1.id,
                profit_month_id="202602",
                revenue_sum_micro_usdc=11,
                expense_sum_micro_usdc=3,
                profit_sum_micro_usdc=8,
                profit_nonnegative=True,
                note=None,
                computed_at=datetime(2026, 2, 1, 0, 2, 0, tzinfo=timezone.utc),
            )
        )
        db.add(
            ProjectSettlement(
                project_id=p2.id,
                profit_month_id="202602",
                revenue_sum_micro_usdc=5,
                expense_sum_micro_usdc=1,
                profit_sum_micro_usdc=4,
                profit_nonnegative=True,
                note=None,
                computed_at=datetime(2026, 2, 1, 0, 1, 0, tzinfo=timezone.utc),
            )
        )
        db.commit()

    r = _client.get("/api/v1/settlement/202602/consolidated")
    assert r.status_code == 200
    body = r.json()
    assert body["success"] is True
    assert body["data"]["profit_month_id"] == "202602"
    assert body["data"]["platform"]["ready"] is True

    projects = body["data"]["projects"]
    assert len(projects) == 2
    p1 = next(p for p in projects if p["project_id"] == "proj_1")
    assert p1["revenue_sum_micro_usdc"] == 11  # latest
    assert body["data"]["sums"]["projects_revenue_sum_micro_usdc"] == 16
    assert body["data"]["sums"]["projects_expense_sum_micro_usdc"] == 4
    assert body["data"]["sums"]["projects_profit_sum_micro_usdc"] == 12

