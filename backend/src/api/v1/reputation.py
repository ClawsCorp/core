from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from src.api.v1.dependencies import require_agent_auth
from src.core.database import get_db
from src.models.agent import Agent
from src.models.reputation_ledger import ReputationLedger
from src.schemas.reputation import ReputationLedgerData, ReputationLedgerEntry, ReputationLedgerResponse

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

    target_agent = (
        db.query(Agent).filter(Agent.agent_id == target_agent_id).first()
    )
    if not target_agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    query = db.query(ReputationLedger).filter(
        ReputationLedger.agent_id == target_agent.id
    )
    total = query.count()
    entries = (
        query.order_by(ReputationLedger.created_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )
    items = [
        ReputationLedgerEntry(
            agent_id=target_agent.agent_id,
            delta=entry.delta,
            reason=entry.reason,
            ref_type=entry.ref_type,
            ref_id=entry.ref_id,
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
