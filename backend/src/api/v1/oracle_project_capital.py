from __future__ import annotations

import re
import secrets
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from src.api.v1.dependencies import require_oracle_hmac
from src.core.audit import record_audit
from src.core.database import get_db
from src.models.project import Project
from src.models.project_capital_event import ProjectCapitalEvent
from src.schemas.project_capital import (
    ProjectCapitalEventCreateRequest,
    ProjectCapitalEventDetailResponse,
    ProjectCapitalEventPublic,
)

router = APIRouter(prefix="/api/v1/oracle", tags=["oracle-project-capital"])

_MONTH_RE = re.compile(r"^\d{6}$")
_TX_HASH_RE = re.compile(r"^0x[a-fA-F0-9]+$")


@router.post("/project-capital-events", response_model=ProjectCapitalEventDetailResponse)
async def create_project_capital_event(
    payload: ProjectCapitalEventCreateRequest,
    request: Request,
    _: str = Depends(require_oracle_hmac),
    db: Session = Depends(get_db),
) -> ProjectCapitalEventDetailResponse:
    if payload.profit_month_id is not None:
        _validate_month(payload.profit_month_id)
    _validate_tx_hash(payload.evidence_tx_hash)
    if payload.delta_micro_usdc == 0:
        raise HTTPException(status_code=400, detail="delta_micro_usdc must be non-zero")

    existing = (
        db.query(ProjectCapitalEvent)
        .filter(ProjectCapitalEvent.idempotency_key == payload.idempotency_key)
        .first()
    )
    request_id = request.headers.get("X-Request-ID") or str(uuid4())
    body_hash = request.state.body_hash

    if existing is not None:
        _record_oracle_audit(request, db, body_hash, request_id, payload.idempotency_key)
        return ProjectCapitalEventDetailResponse(success=True, data=_event_public(db, existing))

    project = db.query(Project).filter(Project.project_id == payload.project_id).first()
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")

    event = ProjectCapitalEvent(
        event_id=_generate_event_id(db),
        idempotency_key=payload.idempotency_key,
        profit_month_id=payload.profit_month_id,
        project_id=project.id,
        delta_micro_usdc=payload.delta_micro_usdc,
        source=payload.source,
        evidence_tx_hash=payload.evidence_tx_hash,
        evidence_url=payload.evidence_url,
    )
    db.add(event)
    db.commit()
    db.refresh(event)

    _record_oracle_audit(request, db, body_hash, request_id, payload.idempotency_key)
    return ProjectCapitalEventDetailResponse(success=True, data=_event_public(db, event))


def _generate_event_id(db: Session) -> str:
    for _ in range(5):
        candidate = f"pce_{secrets.token_hex(8)}"
        if db.query(ProjectCapitalEvent).filter(ProjectCapitalEvent.event_id == candidate).first() is None:
            return candidate
    raise RuntimeError("Failed to generate unique event id.")


def _validate_month(profit_month_id: str) -> None:
    if not _MONTH_RE.fullmatch(profit_month_id):
        raise HTTPException(status_code=400, detail="profit_month_id must use YYYYMM format")
    month = int(profit_month_id[4:6])
    if month < 1 or month > 12:
        raise HTTPException(status_code=400, detail="profit_month_id month must be 01..12")


def _validate_tx_hash(tx_hash: str | None) -> None:
    if tx_hash is None:
        return
    if not _TX_HASH_RE.fullmatch(tx_hash):
        raise HTTPException(status_code=400, detail="evidence_tx_hash must look like a 0x-prefixed hex string")


def _record_oracle_audit(
    request: Request,
    db: Session,
    body_hash: str,
    request_id: str,
    idempotency_key: str,
) -> None:
    signature_status = getattr(request.state, "signature_status", "invalid")
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


def _event_public(db: Session, event: ProjectCapitalEvent) -> ProjectCapitalEventPublic:
    project = db.query(Project).filter(Project.id == event.project_id).first()
    return ProjectCapitalEventPublic(
        event_id=event.event_id,
        idempotency_key=event.idempotency_key,
        project_id=project.project_id if project else "",
        delta_micro_usdc=event.delta_micro_usdc,
        source=event.source,
        profit_month_id=event.profit_month_id,
        evidence_tx_hash=event.evidence_tx_hash,
        evidence_url=event.evidence_url,
        created_at=event.created_at,
    )
