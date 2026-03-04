from __future__ import annotations

from typing import Literal

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
    ReputationPolicyData,
    ReputationPolicyResponse,
    ReputationPolicySourcePublic,
)
from src.services.reputation_policy import (
    PLATFORM_INVESTOR_POINTS_FORMULA,
    PROJECT_INVESTOR_POINTS_FORMULA,
    REPUTATION_CATEGORIES,
    REPUTATION_SOURCE_POLICIES,
    category_points_from_source_totals,
    empty_category_points,
)

router = APIRouter(prefix="/api/v1/reputation", tags=["reputation"])


@router.get("/policy", response_model=ReputationPolicyResponse)
def get_reputation_policy() -> ReputationPolicyResponse:
    return ReputationPolicyResponse(
        success=True,
        data=ReputationPolicyData(
            categories=list(REPUTATION_CATEGORIES),
            investor_project_funding_formula=PROJECT_INVESTOR_POINTS_FORMULA,
            investor_platform_funding_formula=PLATFORM_INVESTOR_POINTS_FORMULA,
            sources=[
                ReputationPolicySourcePublic(
                    source=row.source,
                    category=row.category,
                    description=row.description,
                    default_delta_points=row.default_delta_points,
                    formula=row.formula,
                    status=row.status,
                )
                for row in REPUTATION_SOURCE_POLICIES
            ],
        ),
    )


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
    category_totals = _load_category_points_for_agent_ids(db, [agent.id]).get(agent.id, empty_category_points())

    return ReputationAgentSummaryResponse(
        success=True,
        data=ReputationAgentSummary(
            agent_num=agent.id,
            agent_id=agent.agent_id,
            agent_name=agent.name,
            total_points=int(total_points),
            general_points=int(category_totals["general"]),
            governance_points=int(category_totals["governance"]),
            delivery_points=int(category_totals["delivery"]),
            investor_points=int(category_totals["investor"]),
            commercial_points=int(category_totals["commercial"]),
            safety_points=int(category_totals["safety"]),
            events_count=int(events_count),
            last_event_at=last_event_at,
        ),
    )


@router.get("/leaderboard", response_model=ReputationLeaderboardResponse)
def get_reputation_leaderboard(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    sort: Literal["total", "investor", "governance", "delivery"] = Query("total"),
    db: Session = Depends(get_db),
) -> ReputationLeaderboardResponse:
    rows_query = (
        db.query(
            Agent.id.label("agent_num"),
            Agent.agent_id.label("public_agent_id"),
            Agent.name.label("agent_name"),
            func.coalesce(func.sum(ReputationEvent.delta_points), 0).label("total_points"),
            func.count(ReputationEvent.id).label("events_count"),
            func.max(ReputationEvent.created_at).label("last_event_at"),
        )
        .outerjoin(ReputationEvent, ReputationEvent.agent_id == Agent.id)
        .group_by(Agent.id, Agent.agent_id, Agent.name)
    )

    all_rows = rows_query.all()
    total = len(all_rows)
    category_totals = _load_category_points_for_agent_ids(db, [int(row.agent_num) for row in all_rows])

    materialized_items = [
        ReputationAgentSummary(
            agent_num=int(row.agent_num),
            agent_id=row.public_agent_id,
            agent_name=row.agent_name,
            total_points=int(row.total_points),
            general_points=int(category_totals.get(int(row.agent_num), empty_category_points())["general"]),
            governance_points=int(category_totals.get(int(row.agent_num), empty_category_points())["governance"]),
            delivery_points=int(category_totals.get(int(row.agent_num), empty_category_points())["delivery"]),
            investor_points=int(category_totals.get(int(row.agent_num), empty_category_points())["investor"]),
            commercial_points=int(category_totals.get(int(row.agent_num), empty_category_points())["commercial"]),
            safety_points=int(category_totals.get(int(row.agent_num), empty_category_points())["safety"]),
            events_count=int(row.events_count),
            last_event_at=row.last_event_at,
        )
        for row in all_rows
    ]
    materialized_items.sort(key=lambda item: _leaderboard_sort_key(item, sort))
    items = materialized_items[offset : offset + limit]

    return ReputationLeaderboardResponse(
        success=True,
        data=ReputationLeaderboardData(items=items, limit=limit, offset=offset, total=total),
    )


def _load_category_points_for_agent_ids(db: Session, agent_db_ids: list[int]) -> dict[int, dict[str, int]]:
    if not agent_db_ids:
        return {}

    rows = (
        db.query(
            ReputationEvent.agent_id,
            ReputationEvent.source,
            func.coalesce(func.sum(ReputationEvent.delta_points), 0).label("total_points"),
        )
        .filter(ReputationEvent.agent_id.in_(agent_db_ids))
        .group_by(ReputationEvent.agent_id, ReputationEvent.source)
        .all()
    )
    by_agent: dict[int, list[tuple[str | None, int]]] = {int(agent_id): [] for agent_id in agent_db_ids}
    for row in rows:
        by_agent.setdefault(int(row.agent_id), []).append((row.source, int(row.total_points or 0)))
    return {
        agent_id: category_points_from_source_totals(source_totals)
        for agent_id, source_totals in by_agent.items()
    }


def _leaderboard_sort_key(item: ReputationAgentSummary, sort: str) -> tuple[int, int, int]:
    if sort == "investor":
        primary = int(item.investor_points)
    elif sort == "governance":
        primary = int(item.governance_points)
    elif sort == "delivery":
        primary = int(item.delivery_points)
    else:
        primary = int(item.total_points)
    return (-primary, -int(item.total_points), int(item.agent_num))
