from __future__ import annotations

from sqlalchemy import func
from sqlalchemy.orm import Session

from models.reputation_ledger import ReputationLedger


def get_agent_reputation(db: Session, agent_id: int) -> int:
    total = (
        db.query(func.coalesce(func.sum(ReputationLedger.delta), 0))
        .filter(ReputationLedger.agent_id == agent_id)
        .scalar()
    )
    total = int(total or 0)
    return max(total, 0)
