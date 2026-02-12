from __future__ import annotations

from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from src.core.audit import record_audit
from src.core.config import get_settings
from src.core.database import get_db
from src.core.security import hash_body, verify_hmac_v1
from src.models.agent import Agent
from src.models.reputation_event import ReputationEvent
from src.schemas.reputation import (
    ReputationEventCreateRequest,
    ReputationEventDetailResponse,
    ReputationEventPublic,
)

router = APIRouter(prefix="/api/v1/oracle", tags=["oracle-reputation"])


@router.post("/reputation-events", response_model=ReputationEventDetailResponse)
async def create_reputation_event(
    payload: ReputationEventCreateRequest,
    request: Request,
    db: Session = Depends(get_db),
) -> ReputationEventDetailResponse:
    if payload.delta_points == 0:
        raise HTTPException(status_code=400, detail="delta_points must be non-zero")

    request_id = request.headers.get("X-Request-ID") or str(uuid4())
    body_hash = hash_body(await request.body())
    signature_status = _signature_status(request, body_hash)

    _record_oracle_audit(
        request=request,
        db=db,
        body_hash=body_hash,
        request_id=request_id,
        idempotency_key=payload.idempotency_key,
        signature_status=signature_status,
    )
    if signature_status != "valid":
        raise HTTPException(status_code=403, detail="Invalid signature.")

    agent = db.query(Agent).filter(Agent.agent_id == payload.agent_id).first()
    if agent is None:
        raise HTTPException(status_code=404, detail="Agent not found")

    existing = (
        db.query(ReputationEvent)
        .filter(ReputationEvent.idempotency_key == payload.idempotency_key)
        .first()
    )
    if existing is not None:
        return ReputationEventDetailResponse(success=True, data=_public_event(agent.agent_id, existing))

    existing_by_event_id = (
        db.query(ReputationEvent).filter(ReputationEvent.event_id == payload.event_id).first()
    )
    if existing_by_event_id is not None:
        existing_agent = db.query(Agent).filter(Agent.id == existing_by_event_id.agent_id).first()
        public_agent_id = existing_agent.agent_id if existing_agent else payload.agent_id
        return ReputationEventDetailResponse(
            success=True,
            data=_public_event(public_agent_id, existing_by_event_id),
        )

    event = ReputationEvent(
        event_id=payload.event_id,
        idempotency_key=payload.idempotency_key,
        agent_id=agent.id,
        delta_points=payload.delta_points,
        source=payload.source,
        ref_type=payload.ref_type,
        ref_id=payload.ref_id,
        note=payload.note,
    )
    db.add(event)
    db.commit()
    db.refresh(event)

    return ReputationEventDetailResponse(success=True, data=_public_event(agent.agent_id, event))


def _signature_status(request: Request, body_hash: str) -> str:
    timestamp = request.headers.get("X-Request-Timestamp")
    signature = request.headers.get("X-Signature")
    if not timestamp or not signature:
        return "none"

    settings = get_settings()
    if not settings.oracle_hmac_secret:
        return "invalid"

    if not verify_hmac_v1(settings.oracle_hmac_secret, timestamp, body_hash, signature):
        return "invalid"

    return "valid"


def _record_oracle_audit(
    request: Request,
    db: Session,
    body_hash: str,
    request_id: str,
    idempotency_key: str,
    signature_status: str,
) -> None:
    record_audit(
        db,
        actor_type="oracle",
        agent_id=None,
        method=request.method,
        path=request.url.path,
        idempotency_key=idempotency_key,
        body_hash=body_hash,
        signature_status=signature_status,
        request_id=request_id,
    )


def _public_event(agent_id: str, event: ReputationEvent) -> ReputationEventPublic:
    return ReputationEventPublic(
        event_id=event.event_id,
        idempotency_key=event.idempotency_key,
        agent_id=agent_id,
        delta_points=event.delta_points,
        source=event.source,
        ref_type=event.ref_type,
        ref_id=event.ref_id,
        note=event.note,
        created_at=event.created_at,
    )
