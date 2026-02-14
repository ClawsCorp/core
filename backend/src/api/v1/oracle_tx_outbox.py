from __future__ import annotations

import json
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import update
from sqlalchemy.orm import Session

from src.api.v1.dependencies import require_oracle_hmac
from src.core.audit import record_audit
from src.core.database import get_db
from src.core.tx_outbox import enqueue_tx_outbox_task
from src.core.security import hash_body
from src.models.tx_outbox import TxOutbox
from src.schemas.tx_outbox import (
    TxOutboxClaimRequest,
    TxOutboxClaimResponse,
    TxOutboxClaimData,
    TxOutboxCompleteRequest,
    TxOutboxCompleteResponse,
    TxOutboxEnqueueRequest,
    TxOutboxPendingResponse,
    TxOutboxTask,
    TxOutboxTaskResponse,
)

router = APIRouter(prefix="/api/v1/oracle/tx-outbox", tags=["oracle-tx-outbox"])


def _to_task(row: TxOutbox) -> TxOutboxTask:
    return TxOutboxTask(
        task_id=row.task_id,
        idempotency_key=row.idempotency_key,
        task_type=row.task_type,
        payload=json.loads(row.payload_json or "{}"),
        status=row.status,
        attempts=row.attempts,
        last_error_hint=row.last_error_hint,
        locked_at=row.locked_at,
        locked_by=row.locked_by,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


@router.post("", response_model=TxOutboxTaskResponse)
async def enqueue_task(
    payload: TxOutboxEnqueueRequest,
    request: Request,
    _: str = Depends(require_oracle_hmac),
    db: Session = Depends(get_db),
) -> TxOutboxTaskResponse:
    body_hash = hash_body(await request.body())

    row = enqueue_tx_outbox_task(
        db,
        task_type=payload.task_type,
        payload=payload.payload,
        idempotency_key=payload.idempotency_key,
    )

    record_audit(
        db,
        actor_type="oracle",
        agent_id=None,
        method=request.method,
        path=request.url.path,
        idempotency_key=request.headers.get("Idempotency-Key") or payload.idempotency_key,
        body_hash=body_hash,
        signature_status=getattr(request.state, "signature_status", "none"),
        request_id=request.headers.get("X-Request-Id") or request.headers.get("X-Request-ID"),
        commit=False,
    )
    db.commit()
    db.refresh(row)

    return TxOutboxTaskResponse(success=True, data=_to_task(row))

@router.get("/pending", response_model=TxOutboxPendingResponse)
def list_pending(
    limit: int = 20,
    _: str = Depends(require_oracle_hmac),
    db: Session = Depends(get_db),
) -> TxOutboxPendingResponse:
    limit = max(1, min(int(limit), 100))
    rows = (
        db.query(TxOutbox)
        .filter(TxOutbox.status == "pending")
        .order_by(TxOutbox.id.asc())
        .limit(limit)
        .all()
    )
    return TxOutboxPendingResponse(success=True, data={"items": [_to_task(r) for r in rows], "limit": limit})


@router.post("/claim-next", response_model=TxOutboxClaimResponse)
async def claim_next(
    payload: TxOutboxClaimRequest,
    request: Request,
    _: str = Depends(require_oracle_hmac),
    db: Session = Depends(get_db),
) -> TxOutboxClaimResponse:
    body_hash = hash_body(await request.body())

    candidate = (
        db.query(TxOutbox)
        .filter(TxOutbox.status == "pending")
        .order_by(TxOutbox.id.asc())
        .first()
    )
    if candidate is None:
        record_audit(
            db,
            actor_type="oracle",
            agent_id=None,
            method=request.method,
            path=request.url.path,
            idempotency_key=request.headers.get("Idempotency-Key"),
            body_hash=body_hash,
            signature_status=getattr(request.state, "signature_status", "none"),
            request_id=request.headers.get("X-Request-Id") or request.headers.get("X-Request-ID"),
            commit=False,
        )
        db.commit()
        return TxOutboxClaimResponse(success=False, data=TxOutboxClaimData(task=None, blocked_reason="no_tasks"))

    now = datetime.now(timezone.utc)
    stmt = (
        update(TxOutbox)
        .where(TxOutbox.id == candidate.id, TxOutbox.status == "pending", TxOutbox.locked_at.is_(None))
        .values(
            status="processing",
            locked_at=now,
            locked_by=payload.worker_id,
            attempts=int(candidate.attempts or 0) + 1,
        )
    )
    result = db.execute(stmt)
    if getattr(result, "rowcount", 0) != 1:
        db.rollback()
        return TxOutboxClaimResponse(success=False, data=TxOutboxClaimData(task=None, blocked_reason="race_lost"))

    record_audit(
        db,
        actor_type="oracle",
        agent_id=None,
        method=request.method,
        path=request.url.path,
        idempotency_key=request.headers.get("Idempotency-Key"),
        body_hash=body_hash,
        signature_status=getattr(request.state, "signature_status", "none"),
        request_id=request.headers.get("X-Request-Id") or request.headers.get("X-Request-ID"),
        commit=False,
    )
    db.commit()

    row = db.query(TxOutbox).filter(TxOutbox.id == candidate.id).first()
    if not row:
        return TxOutboxClaimResponse(success=False, data=TxOutboxClaimData(task=None, blocked_reason="not_found"))
    return TxOutboxClaimResponse(success=True, data=TxOutboxClaimData(task=_to_task(row), blocked_reason=None))


@router.get("/{task_id}", response_model=TxOutboxTaskResponse)
def get_task(task_id: str, db: Session = Depends(get_db)) -> TxOutboxTaskResponse:
    row = db.query(TxOutbox).filter(TxOutbox.task_id == task_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Task not found")
    return TxOutboxTaskResponse(success=True, data=_to_task(row))


@router.post("/{task_id}/claim", response_model=TxOutboxClaimResponse)
async def claim_task(
    task_id: str,
    payload: TxOutboxClaimRequest,
    request: Request,
    _: str = Depends(require_oracle_hmac),
    db: Session = Depends(get_db),
) -> TxOutboxClaimResponse:
    body_hash = hash_body(await request.body())

    row = db.query(TxOutbox).filter(TxOutbox.task_id == task_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Task not found")
    if row.status != "pending":
        return TxOutboxClaimResponse(success=False, data=TxOutboxClaimData(task=None, blocked_reason="not_pending"))
    if row.locked_at is not None:
        return TxOutboxClaimResponse(success=False, data=TxOutboxClaimData(task=None, blocked_reason="locked"))

    row.status = "processing"
    row.locked_at = datetime.now(timezone.utc)
    row.locked_by = payload.worker_id
    row.attempts = int(row.attempts or 0) + 1

    record_audit(
        db,
        actor_type="oracle",
        agent_id=None,
        method=request.method,
        path=request.url.path,
        idempotency_key=request.headers.get("Idempotency-Key"),
        body_hash=body_hash,
        signature_status=getattr(request.state, "signature_status", "none"),
        request_id=request.headers.get("X-Request-Id") or request.headers.get("X-Request-ID"),
        commit=False,
    )
    db.commit()
    db.refresh(row)

    return TxOutboxClaimResponse(success=True, data=TxOutboxClaimData(task=_to_task(row), blocked_reason=None))


@router.post("/{task_id}/complete", response_model=TxOutboxCompleteResponse)
async def complete_task(
    task_id: str,
    payload: TxOutboxCompleteRequest,
    request: Request,
    _: str = Depends(require_oracle_hmac),
    db: Session = Depends(get_db),
) -> TxOutboxCompleteResponse:
    body_hash = hash_body(await request.body())

    row = db.query(TxOutbox).filter(TxOutbox.task_id == task_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Task not found")
    if row.status not in {"processing", "pending"}:
        raise HTTPException(status_code=409, detail="Task is already finalized")

    if payload.status not in {"succeeded", "failed"}:
        raise HTTPException(status_code=400, detail="status must be succeeded|failed")

    row.status = payload.status
    row.last_error_hint = payload.error_hint

    record_audit(
        db,
        actor_type="oracle",
        agent_id=None,
        method=request.method,
        path=request.url.path,
        idempotency_key=request.headers.get("Idempotency-Key"),
        body_hash=body_hash,
        signature_status=getattr(request.state, "signature_status", "none"),
        request_id=request.headers.get("X-Request-Id") or request.headers.get("X-Request-ID"),
        commit=False,
    )
    db.commit()
    db.refresh(row)

    return TxOutboxCompleteResponse(success=True, data=_to_task(row))
