from __future__ import annotations

from sqlalchemy import func
from sqlalchemy.orm import Session

from src.models.project_capital_event import ProjectCapitalEvent


def get_project_capital_balance_micro_usdc(db: Session, project_id: int) -> int:
    balance = (
        db.query(func.coalesce(func.sum(ProjectCapitalEvent.delta_micro_usdc), 0))
        .filter(ProjectCapitalEvent.project_id == project_id)
        .scalar()
    )
    return int(balance or 0)
