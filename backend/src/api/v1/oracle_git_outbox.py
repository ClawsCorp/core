# SPDX-License-Identifier: BSL-1.1

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import update
from sqlalchemy.orm import Session

from src.api.v1.dependencies import require_oracle_hmac
from src.core.audit import record_audit
from src.core.config import get_settings
from src.core.database import get_db
from src.core.git_outbox import enqueue_git_outbox_task
from src.core.security import hash_body
from src.models.git_outbox import GitOutbox
from src.schemas.git_outbox import (
    GitOutboxClaimData,
    GitOutboxClaimRequest,
    GitOutboxClaimResponse,
    GitOutboxCompleteRequest,
    GitOutboxCompleteResponse,
    GitOutboxEnqueueRequest,
    GitOutboxPendingResponse,
    GitOutboxTask,
    GitOutboxTaskResponse,
    GitOutboxUpdateRequest,
)

router = APIRouter(prefix="/api/v1/oracle/git-outbox", tags=["oracle-git-outbox"])


def _to_task(row: GitOutbox) -> GitOutboxTask:
    result_obj: dict | None = None
    pr_url: str | None = None
    if row.result_json:
        try:
            parsed = json.loads(row.result_json)
            if isinstance(parsed, dict):
                result_obj = parsed
                parsed_pr_url = parsed.get("pr_url")
                if isinstance(parsed_pr_url, str) and parsed_pr_url.strip():
                    pr_url = parsed_pr_url.strip()
        except ValueError:
            result_obj = None
    return GitOutboxTask(
        task_id=row.task_id,
        idempotency_key=row.idempotency_key,
        project_num=row.project_id,
        requested_by_agent_num=row.requested_by_agent_id,
        task_type=row.task_type,
        payload=json.loads(row.payload_json or "{}"),
        result=result_obj,
        branch_name=row.branch_name,
        commit_sha=row.commit_sha,
        pr_url=pr_url,
        status=row.status,
        attempts=row.attempts,
        last_error_hint=row.last_error_hint,
        locked_at=row.locked_at,
        locked_by=row.locked_by,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


@router.post("", response_model=GitOutboxTaskResponse)
async def enqueue_task(
    payload: GitOutboxEnqueueRequest,
    request: Request,
    _: str = Depends(require_oracle_hmac),
    db: Session = Depends(get_db),
) -> GitOutboxTaskResponse:
    body_hash = hash_body(await request.body())
    row = enqueue_git_outbox_task(
        db,
        task_type=payload.task_type,
        payload=payload.payload,
        idempotency_key=payload.idempotency_key,
        project_id=payload.project_num,
        requested_by_agent_id=payload.requested_by_agent_num,
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
    return GitOutboxTaskResponse(success=True, data=_to_task(row))


@router.get("/pending", response_model=GitOutboxPendingResponse)
def list_pending(
    limit: int = 20,
    _: str = Depends(require_oracle_hmac),
    db: Session = Depends(get_db),
) -> GitOutboxPendingResponse:
    limit = max(1, min(int(limit), 100))
    rows = (
        db.query(GitOutbox)
        .filter(GitOutbox.status == "pending")
        .order_by(GitOutbox.id.asc())
        .limit(limit)
        .all()
    )
    return GitOutboxPendingResponse(success=True, data={"items": [_to_task(r) for r in rows], "limit": limit})


@router.post("/claim-next", response_model=GitOutboxClaimResponse)
async def claim_next(
    payload: GitOutboxClaimRequest,
    request: Request,
    _: str = Depends(require_oracle_hmac),
    db: Session = Depends(get_db),
) -> GitOutboxClaimResponse:
    body_hash = hash_body(await request.body())

    settings = get_settings()
    ttl = int(getattr(settings, "tx_outbox_lock_ttl_seconds", 300) or 300)
    now = datetime.now(timezone.utc)
    stale_before = now - timedelta(seconds=max(1, ttl))

    candidate = (
        db.query(GitOutbox)
        .filter(GitOutbox.status == "pending", GitOutbox.locked_at.is_(None))
        .order_by(GitOutbox.id.asc())
        .first()
    )
    is_reclaim = False
    if candidate is None:
        processing = (
            db.query(GitOutbox)
            .filter(GitOutbox.status == "processing", GitOutbox.locked_at.isnot(None))
            .order_by(GitOutbox.id.asc())
            .first()
        )
        if processing is not None:
            locked_at = processing.locked_at
            if locked_at is not None and locked_at.tzinfo is None:
                locked_at = locked_at.replace(tzinfo=timezone.utc)
            if locked_at is not None and locked_at < stale_before:
                candidate = processing
                is_reclaim = True

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
        return GitOutboxClaimResponse(success=False, data=GitOutboxClaimData(task=None, blocked_reason="no_tasks"))

    stmt = (
        update(GitOutbox)
        .where(
            GitOutbox.id == candidate.id,
            ((GitOutbox.status == "pending") & (GitOutbox.locked_at.is_(None)))
            if not is_reclaim
            else ((GitOutbox.status == "processing") & (GitOutbox.locked_at == candidate.locked_at)),
        )
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
        return GitOutboxClaimResponse(success=False, data=GitOutboxClaimData(task=None, blocked_reason="race_lost"))

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

    row = db.query(GitOutbox).filter(GitOutbox.id == candidate.id).first()
    if not row:
        return GitOutboxClaimResponse(success=False, data=GitOutboxClaimData(task=None, blocked_reason="not_found"))
    return GitOutboxClaimResponse(success=True, data=GitOutboxClaimData(task=_to_task(row), blocked_reason=None))


@router.get("/{task_id}", response_model=GitOutboxTaskResponse)
def get_task(task_id: str, db: Session = Depends(get_db)) -> GitOutboxTaskResponse:
    row = db.query(GitOutbox).filter(GitOutbox.task_id == task_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Task not found")
    return GitOutboxTaskResponse(success=True, data=_to_task(row))


@router.post("/{task_id}/claim", response_model=GitOutboxClaimResponse)
async def claim_task(
    task_id: str,
    payload: GitOutboxClaimRequest,
    request: Request,
    _: str = Depends(require_oracle_hmac),
    db: Session = Depends(get_db),
) -> GitOutboxClaimResponse:
    body_hash = hash_body(await request.body())

    row = db.query(GitOutbox).filter(GitOutbox.task_id == task_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Task not found")
    if row.status != "pending":
        return GitOutboxClaimResponse(success=False, data=GitOutboxClaimData(task=None, blocked_reason="not_pending"))
    if row.locked_at is not None:
        return GitOutboxClaimResponse(success=False, data=GitOutboxClaimData(task=None, blocked_reason="locked"))

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
    return GitOutboxClaimResponse(success=True, data=GitOutboxClaimData(task=_to_task(row), blocked_reason=None))


@router.post("/{task_id}/complete", response_model=GitOutboxCompleteResponse)
async def complete_task(
    task_id: str,
    payload: GitOutboxCompleteRequest,
    request: Request,
    _: str = Depends(require_oracle_hmac),
    db: Session = Depends(get_db),
) -> GitOutboxCompleteResponse:
    body_hash = hash_body(await request.body())

    row = db.query(GitOutbox).filter(GitOutbox.task_id == task_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Task not found")
    if row.status not in {"processing", "pending"}:
        raise HTTPException(status_code=409, detail="Task is already finalized")
    if payload.status not in {"succeeded", "failed"}:
        raise HTTPException(status_code=400, detail="status must be succeeded|failed")

    row.status = payload.status
    row.last_error_hint = payload.error_hint
    if payload.result is not None:
        row.result_json = json.dumps(payload.result, separators=(",", ":"), sort_keys=True)
    if payload.branch_name:
        row.branch_name = payload.branch_name
    if payload.commit_sha:
        row.commit_sha = payload.commit_sha

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
    return GitOutboxCompleteResponse(success=True, data=_to_task(row))


@router.post("/{task_id}/update", response_model=GitOutboxTaskResponse)
async def update_task(
    task_id: str,
    payload: GitOutboxUpdateRequest,
    request: Request,
    _: str = Depends(require_oracle_hmac),
    db: Session = Depends(get_db),
) -> GitOutboxTaskResponse:
    body_hash = hash_body(await request.body())

    row = db.query(GitOutbox).filter(GitOutbox.task_id == task_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Task not found")
    if row.status not in {"processing", "pending"}:
        raise HTTPException(status_code=409, detail="Task is already finalized")

    if payload.result is not None:
        row.result_json = json.dumps(payload.result, separators=(",", ":"), sort_keys=True)
    if payload.branch_name:
        row.branch_name = payload.branch_name
    if payload.commit_sha:
        row.commit_sha = payload.commit_sha

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
    return GitOutboxTaskResponse(success=True, data=_to_task(row))
