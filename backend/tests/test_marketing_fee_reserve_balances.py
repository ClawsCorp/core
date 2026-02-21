from __future__ import annotations

import sys
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from src.core.database import Base

import src.models  # noqa: F401
from src.models.expense_event import ExpenseEvent
from src.models.marketing_fee_accrual_event import MarketingFeeAccrualEvent
from src.models.project import Project, ProjectStatus
from src.models.project_capital_event import ProjectCapitalEvent
from src.models.revenue_event import RevenueEvent
from src.services.project_capital import (
    get_project_capital_balance_micro_usdc,
    get_project_capital_spendable_balance_micro_usdc,
)
from src.services.project_revenue import (
    get_project_revenue_balance_micro_usdc,
    get_project_revenue_spendable_balance_micro_usdc,
)


def _session() -> sessionmaker[Session]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    session_local = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    Base.metadata.create_all(bind=engine)
    return session_local


def test_marketing_fee_reserve_reduces_spendable_project_balances() -> None:
    SessionLocal = _session()

    with SessionLocal() as db:
        project = Project(project_id="prj_mfee", slug="mfee", name="Marketing", status=ProjectStatus.active)
        db.add(project)
        db.flush()

        db.add(
            ProjectCapitalEvent(
                event_id="pc_1",
                idempotency_key="pc_1",
                profit_month_id="202602",
                project_id=project.id,
                delta_micro_usdc=10_000,
                source="treasury_usdc_deposit",
            )
        )
        db.add(
            RevenueEvent(
                event_id="rev_1",
                idempotency_key="rev_1",
                profit_month_id="202602",
                project_id=project.id,
                amount_micro_usdc=8_000,
                source="customer_billing_usdc_transfer",
            )
        )
        db.add(
            ExpenseEvent(
                event_id="exp_1",
                idempotency_key="exp_1",
                profit_month_id="202602",
                project_id=project.id,
                amount_micro_usdc=1_000,
                category="project_bounty_payout_revenue",
            )
        )
        db.add(
            MarketingFeeAccrualEvent(
                event_id="mfee_cap",
                idempotency_key="mfee_cap",
                project_id=project.id,
                profit_month_id="202602",
                bucket="project_capital",
                source="treasury_usdc_deposit",
                gross_amount_micro_usdc=10_000,
                fee_amount_micro_usdc=100,
            )
        )
        db.add(
            MarketingFeeAccrualEvent(
                event_id="mfee_rev",
                idempotency_key="mfee_rev",
                project_id=project.id,
                profit_month_id="202602",
                bucket="project_revenue",
                source="customer_billing_usdc_transfer",
                gross_amount_micro_usdc=8_000,
                fee_amount_micro_usdc=80,
            )
        )
        db.commit()

        assert get_project_capital_balance_micro_usdc(db, project.id) == 10_000
        assert get_project_capital_spendable_balance_micro_usdc(db, project.id) == 9_900

        assert get_project_revenue_balance_micro_usdc(db, project.id) == 7_000
        assert get_project_revenue_spendable_balance_micro_usdc(db, project.id) == 6_920
