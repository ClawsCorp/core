from __future__ import annotations

import json
import secrets
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from src.api.v1.dependencies import require_oracle_hmac
from src.core.audit import record_audit
from src.core.database import get_db
from src.core.db_utils import insert_or_get_by_unique
from src.core.security import hash_body
from src.models.tx_outbox import TxOutbox
from src.schemas.tx_outbox import (
    TxOutboxClaimRequest,
    TxOutboxClaimResponse,
    TxOutboxClaimData,
    TxOutboxCompleteRequest,
    TxOutboxCompleteResponse,
    TxOutboxEnqueueRequest,
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


def _new_task_id(db: Session) -> str:
    for _ in range(5):
        candidate = f"txo_{secrets.token_hex(8)}"
        exists = db.query(TxOutbox.id).filter(TxOutbox.task_id == candidate).first()
        if not exists:
            return candidate
    raise RuntimeError("Failed to generate unique task id")


@router.post("", response_model=TxOutboxTaskResponse)
async def enqueue_task(
    payload: TxOutboxEnqueueRequest,
    request: Request,
    _: str = Depends(require_oracle_hmac),
    db: Session = Depends(get_db),
) -> TxOutboxTaskResponse:
    body_hash = hash_body(await request.body())

    row = TxOutbox(
        task_id=_new_task_id(db),
        idempotency_key=payload.idempotency_key,
        task_type=payload.task_type,
        payload_json=json.dumps(payload.payload, separators=(",", ":"), sort_keys=True),
        status="pending",
        attempts=0,
        last_error_hint=None,
        locked_at=None,
        locked_by=None,
    )
    if payload.idempotency_key:
        row, _created = insert_or_get_by_unique(
            db,
            instance=row,
            model=TxOutbox,
            unique_filter={"idempotency_key": payload.idempotency_key},
        )
    else:
        db.add(row)
        db.flush()

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

