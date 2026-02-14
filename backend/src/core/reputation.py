# SPDX-License-Identifier: BSL-1.1

from __future__ import annotations

from sqlalchemy import func
from sqlalchemy.orm import Session

from src.models.reputation_event import ReputationEvent


def get_agent_reputation(db: Session, agent_id: int) -> int:
    total = (
        db.query(func.coalesce(func.sum(ReputationEvent.delta_points), 0))
        .filter(ReputationEvent.agent_id == agent_id)
        .scalar()
    )
    total = int(total or 0)
    return max(total, 0)
