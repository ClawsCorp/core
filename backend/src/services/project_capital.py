from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import func
from sqlalchemy.orm import Session

from src.models.project_capital_event import ProjectCapitalEvent
from src.models.project_capital_reconciliation_report import ProjectCapitalReconciliationReport


def get_project_capital_balance_micro_usdc(db: Session, project_id: int) -> int:
    balance = (
        db.query(func.coalesce(func.sum(ProjectCapitalEvent.delta_micro_usdc), 0))
        .filter(ProjectCapitalEvent.project_id == project_id)
        .scalar()
    )
    return int(balance or 0)


def get_latest_project_capital_reconciliation(
    db: Session, project_id: int
) -> ProjectCapitalReconciliationReport | None:
    return (
        db.query(ProjectCapitalReconciliationReport)
        .filter(ProjectCapitalReconciliationReport.project_id == project_id)
        .order_by(
            ProjectCapitalReconciliationReport.computed_at.desc(),
            ProjectCapitalReconciliationReport.id.desc(),
        )
        .first()
    )


def is_reconciliation_fresh(
    reconciliation: ProjectCapitalReconciliationReport,
    max_age_seconds: int,
    *,
    now: datetime | None = None,
) -> bool:
    reference_now = now or datetime.now(timezone.utc)
    computed_at = reconciliation.computed_at
    if computed_at.tzinfo is None:
        computed_at = computed_at.replace(tzinfo=timezone.utc)
    return computed_at >= (reference_now - timedelta(seconds=max_age_seconds))
