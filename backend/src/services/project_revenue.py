from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import func
from sqlalchemy.orm import Session

from src.models.expense_event import ExpenseEvent
from src.models.project_revenue_reconciliation_report import ProjectRevenueReconciliationReport
from src.models.revenue_event import RevenueEvent
from src.services.marketing_fee import get_project_marketing_fee_reserve_micro_usdc


# MVP: only subtract outflows that are explicitly tied to the project revenue bucket.
REVENUE_OUTFLOW_CATEGORIES: set[str] = {"project_bounty_payout_revenue"}


def get_project_revenue_balance_micro_usdc(db: Session, project_id: int) -> int:
    revenue_sum = (
        db.query(func.coalesce(func.sum(RevenueEvent.amount_micro_usdc), 0))
        .filter(RevenueEvent.project_id == project_id)
        .scalar()
    )
    outflow_sum = (
        db.query(func.coalesce(func.sum(ExpenseEvent.amount_micro_usdc), 0))
        .filter(
            ExpenseEvent.project_id == project_id,
            ExpenseEvent.category.in_(sorted(REVENUE_OUTFLOW_CATEGORIES)),
        )
        .scalar()
    )
    return int(revenue_sum or 0) - int(outflow_sum or 0)


def get_project_revenue_spendable_balance_micro_usdc(db: Session, project_id: int) -> int:
    gross = get_project_revenue_balance_micro_usdc(db, project_id)
    reserved = get_project_marketing_fee_reserve_micro_usdc(db, project_id, bucket="project_revenue")
    return max(gross - reserved, 0)


def get_latest_project_revenue_reconciliation(
    db: Session, project_id: int
) -> ProjectRevenueReconciliationReport | None:
    return (
        db.query(ProjectRevenueReconciliationReport)
        .filter(ProjectRevenueReconciliationReport.project_id == project_id)
        .order_by(
            ProjectRevenueReconciliationReport.computed_at.desc(),
            ProjectRevenueReconciliationReport.id.desc(),
        )
        .first()
    )


def is_reconciliation_fresh(
    reconciliation: ProjectRevenueReconciliationReport,
    max_age_seconds: int,
    *,
    now: datetime | None = None,
) -> bool:
    reference_now = now or datetime.now(timezone.utc)
    computed_at = reconciliation.computed_at
    if computed_at.tzinfo is None:
        computed_at = computed_at.replace(tzinfo=timezone.utc)
    return computed_at >= (reference_now - timedelta(seconds=max_age_seconds))
