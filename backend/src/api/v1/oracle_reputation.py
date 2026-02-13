from __future__ import annotations

from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from src.core.audit import record_audit
from src.core.database import get_db
from src.models.reputation_event import ReputationEvent
from src.schemas.reputation import (
    ReputationEventCreateRequest,
    ReputationEventDetailResponse,
    ReputationEventPublic,
)
from src.api.v1.dependencies import require_oracle_hmac
from src.services.reputation_ingestion import ingest_reputation_event

router = APIRouter(prefix="/api/v1/oracle", tags=["oracle-reputation"])


@router.post("/reputation-events", response_model=ReputationEventDetailResponse)
async def create_reputation_event(
    payload: ReputationEventCreateRequest,
    request: Request,
    _: str = Depends(require_oracle_hmac),
    db: Session = Depends(get_db),
) -> ReputationEventDetailResponse:
    request_id = request.headers.get("X-Request-Id") or str(uuid4())
    body_hash = request.state.body_hash
    signature_status = getattr(request.state, "signature_status", "invalid")

    try:
        event, public_agent_id = ingest_reputation_event(db, payload)
    except ValueError as exc:
        _record_oracle_audit(
            request=request,
            db=db,
            body_hash=body_hash,
            request_id=request_id,
            idempotency_key=payload.idempotency_key,
            signature_status=signature_status,
        )
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except LookupError as exc:
        _record_oracle_audit(
            request=request,
            db=db,
            body_hash=body_hash,
            request_id=request_id,
            idempotency_key=payload.idempotency_key,
            signature_status=signature_status,
        )
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    _record_oracle_audit(
        request=request,
        db=db,
        body_hash=body_hash,
        request_id=request_id,
        idempotency_key=payload.idempotency_key,
        signature_status=signature_status,
        commit=False,
    )
    db.commit()
    db.refresh(event)

    return ReputationEventDetailResponse(success=True, data=_public_event(public_agent_id, event))


def _record_oracle_audit(
    request: Request,
    db: Session,
    body_hash: str,
    request_id: str,
    idempotency_key: str,
    signature_status: str,
    commit: bool = True,
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
        commit=commit,
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
