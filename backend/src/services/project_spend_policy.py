from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import func
from sqlalchemy.orm import Session

from src.models.expense_event import ExpenseEvent
from src.models.project import Project
from src.models.project_spend_policy import ProjectSpendPolicy


@dataclass(frozen=True)
class SpendCaps:
    per_bounty_cap_micro_usdc: int | None
    per_day_cap_micro_usdc: int | None
    per_month_cap_micro_usdc: int | None


def resolve_caps(db: Session, *, project: Project) -> SpendCaps:
    """
    Resolve spend caps for a project.

    Precedence:
    1) explicit ProjectSpendPolicy row (if present)
    2) legacy field Project.monthly_budget_micro_usdc (as per_month cap only)
    """
    row = db.query(ProjectSpendPolicy).filter(ProjectSpendPolicy.project_id == project.id).first()
    if row is not None:
        return SpendCaps(
            per_bounty_cap_micro_usdc=row.per_bounty_cap_micro_usdc,
            per_day_cap_micro_usdc=row.per_day_cap_micro_usdc,
            per_month_cap_micro_usdc=row.per_month_cap_micro_usdc,
        )
    return SpendCaps(
        per_bounty_cap_micro_usdc=None,
        per_day_cap_micro_usdc=None,
        per_month_cap_micro_usdc=int(project.monthly_budget_micro_usdc) if project.monthly_budget_micro_usdc is not None else None,
    )


def check_spend_allowed(
    db: Session,
    *,
    project: Project,
    profit_month_id: str,
    amount_micro_usdc: int,
    now: datetime | None = None,
) -> str | None:
    """
    Return a blocked_reason string if this spend would exceed caps, else None.
    """
    now = now or datetime.now(timezone.utc)
    caps = resolve_caps(db, project=project)

    if caps.per_bounty_cap_micro_usdc is not None and amount_micro_usdc > int(caps.per_bounty_cap_micro_usdc):
        return "project_spend_policy_per_bounty_exceeded"

    if caps.per_month_cap_micro_usdc is not None:
        used = (
            db.query(func.sum(ExpenseEvent.amount_micro_usdc))
            .filter(ExpenseEvent.project_id == project.id, ExpenseEvent.profit_month_id == profit_month_id)
            .scalar()
        )
        used_int = int(used or 0)
        if used_int + int(amount_micro_usdc) > int(caps.per_month_cap_micro_usdc):
            return "project_spend_policy_per_month_exceeded"

    if caps.per_day_cap_micro_usdc is not None:
        day_start = datetime(now.year, now.month, now.day, tzinfo=timezone.utc)
        used = (
            db.query(func.sum(ExpenseEvent.amount_micro_usdc))
            .filter(
                ExpenseEvent.project_id == project.id,
                ExpenseEvent.created_at >= day_start,
                ExpenseEvent.created_at <= now + timedelta(seconds=1),
            )
            .scalar()
        )
        used_int = int(used or 0)
        if used_int + int(amount_micro_usdc) > int(caps.per_day_cap_micro_usdc):
            return "project_spend_policy_per_day_exceeded"

    return None

