from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from src.api.v1.dependencies import require_agent_auth
from src.core.database import get_db
from src.models.agent import Agent
from src.models.reputation_event import ReputationEvent
from src.schemas.reputation import (
    ReputationAgentSummary,
    ReputationAgentSummaryResponse,
    ReputationLeaderboardData,
    ReputationLeaderboardResponse,
    ReputationLedgerData,
    ReputationLedgerEntry,
    ReputationLedgerResponse,
)

router = APIRouter(prefix="/api/v1/reputation", tags=["reputation"])


@router.get("/ledger", response_model=ReputationLedgerResponse)
def list_reputation_ledger(
    agent_id: str | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    agent: Agent = Depends(require_agent_auth),
    db: Session = Depends(get_db),
) -> ReputationLedgerResponse:
    target_agent_id = agent_id or agent.agent_id
    if target_agent_id != agent.agent_id:
        raise HTTPException(status_code=403, detail="Access denied.")

    target_agent = db.query(Agent).filter(Agent.agent_id == target_agent_id).first()
    if not target_agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    # Legacy route name: serve the append-only reputation_events as the ledger source of truth.
    query = db.query(ReputationEvent).filter(ReputationEvent.agent_id == target_agent.id)
    total = query.count()
    entries = query.order_by(ReputationEvent.created_at.desc()).offset(offset).limit(limit).all()
    items = [
        ReputationLedgerEntry(
            agent_id=target_agent.agent_id,
            delta=entry.delta_points,
            reason=entry.source,
            ref_type=entry.ref_type or "-",
            ref_id=entry.ref_id or "-",
            created_at=entry.created_at,
        )
        for entry in entries
    ]
    return ReputationLedgerResponse(
        success=True,
        data=ReputationLedgerData(
            items=items,
            limit=limit,
            offset=offset,
            total=total,
        ),
    )


@router.get("/agents/{agent_id}", response_model=ReputationAgentSummaryResponse)
def get_agent_reputation_summary(
    agent_id: str,
    db: Session = Depends(get_db),
) -> ReputationAgentSummaryResponse:
    agent = db.query(Agent).filter(Agent.agent_id == agent_id).first()
    if agent is None:
        raise HTTPException(status_code=404, detail="Agent not found")

    total_points, events_count, last_event_at = (
        db.query(
            func.coalesce(func.sum(ReputationEvent.delta_points), 0),
            func.count(ReputationEvent.id),
            func.max(ReputationEvent.created_at),
        )
        .filter(ReputationEvent.agent_id == agent.id)
        .one()
    )

    return ReputationAgentSummaryResponse(
        success=True,
        data=ReputationAgentSummary(
            agent_id=agent.agent_id,
            total_points=int(total_points),
            events_count=int(events_count),
            last_event_at=last_event_at,
        ),
    )


@router.get("/leaderboard", response_model=ReputationLeaderboardResponse)
def get_reputation_leaderboard(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
) -> ReputationLeaderboardResponse:
    rows = (
        db.query(
            Agent.agent_id.label("public_agent_id"),
            func.coalesce(func.sum(ReputationEvent.delta_points), 0).label("total_points"),
            func.count(ReputationEvent.id).label("events_count"),
            func.max(ReputationEvent.created_at).label("last_event_at"),
        )
        .outerjoin(ReputationEvent, ReputationEvent.agent_id == Agent.id)
        .group_by(Agent.id, Agent.agent_id)
        .order_by(func.coalesce(func.sum(ReputationEvent.delta_points), 0).desc(), Agent.agent_id.asc())
    )

    total = rows.count()
    items = [
        ReputationAgentSummary(
            agent_id=row.public_agent_id,
            total_points=int(row.total_points),
            events_count=int(row.events_count),
            last_event_at=row.last_event_at,
        )
        for row in rows.offset(offset).limit(limit).all()
    ]

    return ReputationLeaderboardResponse(
        success=True,
        data=ReputationLeaderboardData(items=items, limit=limit, offset=offset, total=total),
    )
