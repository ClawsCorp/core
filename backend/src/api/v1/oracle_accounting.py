from __future__ import annotations

import re
import secrets
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from src.api.v1.dependencies import require_oracle_hmac
from src.core.audit import record_audit
from src.core.database import get_db
from src.models.expense_event import ExpenseEvent
from src.models.project import Project
from src.models.revenue_event import RevenueEvent
from src.schemas.accounting import (
    ExpenseEventCreateRequest,
    ExpenseEventDetailResponse,
    ExpenseEventPublic,
    RevenueEventCreateRequest,
    RevenueEventDetailResponse,
    RevenueEventPublic,
)

router = APIRouter(prefix="/api/v1/oracle", tags=["oracle-accounting"])

_MONTH_RE = re.compile(r"^\d{6}$")
_TX_HASH_RE = re.compile(r"^0x[a-fA-F0-9]+$")


@router.post("/revenue-events", response_model=RevenueEventDetailResponse)
async def create_revenue_event(
    payload: RevenueEventCreateRequest,
    request: Request,
    _: str = Depends(require_oracle_hmac),
    db: Session = Depends(get_db),
) -> RevenueEventDetailResponse:
    _validate_month(payload.profit_month_id)
    _validate_tx_hash(payload.tx_hash)

    request_id = request.headers.get("X-Request-Id") or request.headers.get("X-Request-ID") or str(uuid4())
    body_hash = request.state.body_hash
    try:
        project = _project_by_public_id(db, payload.project_id)
        event = RevenueEvent(
            event_id=_generate_event_id(db, RevenueEvent, "rev_"),
            profit_month_id=payload.profit_month_id,
            project_id=project.id if project else None,
            amount_micro_usdc=payload.amount_micro_usdc,
            tx_hash=payload.tx_hash,
            source=payload.source,
            idempotency_key=payload.idempotency_key,
            evidence_url=payload.evidence_url,
        )
        db.add(event)
        _record_oracle_audit(request, db, body_hash, request_id, payload.idempotency_key, commit=False)
        db.commit()
        db.refresh(event)
    except IntegrityError:
        db.rollback()
        event = (
            db.query(RevenueEvent)
            .filter(RevenueEvent.idempotency_key == payload.idempotency_key)
            .first()
        )
        if event is None:
            raise
        _record_oracle_audit(request, db, body_hash, request_id, payload.idempotency_key)
    except Exception:
        db.rollback()
        raise

    return RevenueEventDetailResponse(success=True, data=_revenue_public(db, event))


@router.post("/expense-events", response_model=ExpenseEventDetailResponse)
async def create_expense_event(
    payload: ExpenseEventCreateRequest,
    request: Request,
    _: str = Depends(require_oracle_hmac),
    db: Session = Depends(get_db),
) -> ExpenseEventDetailResponse:
    _validate_month(payload.profit_month_id)
    _validate_tx_hash(payload.tx_hash)

    request_id = request.headers.get("X-Request-Id") or request.headers.get("X-Request-ID") or str(uuid4())
    body_hash = request.state.body_hash
    try:
        project = _project_by_public_id(db, payload.project_id)
        event = ExpenseEvent(
            event_id=_generate_event_id(db, ExpenseEvent, "exp_"),
            profit_month_id=payload.profit_month_id,
            project_id=project.id if project else None,
            amount_micro_usdc=payload.amount_micro_usdc,
            tx_hash=payload.tx_hash,
            category=payload.category,
            idempotency_key=payload.idempotency_key,
            evidence_url=payload.evidence_url,
        )
        db.add(event)
        _record_oracle_audit(request, db, body_hash, request_id, payload.idempotency_key, commit=False)
        db.commit()
        db.refresh(event)
    except IntegrityError:
        db.rollback()
        event = (
            db.query(ExpenseEvent)
            .filter(ExpenseEvent.idempotency_key == payload.idempotency_key)
            .first()
        )
        if event is None:
            raise
        _record_oracle_audit(request, db, body_hash, request_id, payload.idempotency_key)
    except Exception:
        db.rollback()
        raise

    return ExpenseEventDetailResponse(success=True, data=_expense_public(db, event))


def _generate_event_id(db: Session, model: type[RevenueEvent] | type[ExpenseEvent], prefix: str) -> str:
    for _ in range(5):
        candidate = f"{prefix}{secrets.token_hex(8)}"
        if db.query(model).filter(model.event_id == candidate).first() is None:
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
        raise HTTPException(status_code=400, detail="tx_hash must look like a 0x-prefixed hex string")


def _project_by_public_id(db: Session, project_id: str | None) -> Project | None:
    if project_id is None:
        return None
    project = db.query(Project).filter(Project.project_id == project_id).first()
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


def _record_oracle_audit(
    request: Request,
    db: Session,
    body_hash: str,
    request_id: str,
    idempotency_key: str,
    commit: bool = True,
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
        commit=commit,
    )


def _revenue_public(db: Session, event: RevenueEvent) -> RevenueEventPublic:
    project_id: str | None = None
    if event.project_id is not None:
        project = db.query(Project).filter(Project.id == event.project_id).first()
        project_id = project.project_id if project else None
    return RevenueEventPublic(
        event_id=event.event_id,
        profit_month_id=event.profit_month_id,
        project_id=project_id,
        amount_micro_usdc=event.amount_micro_usdc,
        tx_hash=event.tx_hash,
        source=event.source,
        idempotency_key=event.idempotency_key,
        evidence_url=event.evidence_url,
        created_at=event.created_at,
    )


def _expense_public(db: Session, event: ExpenseEvent) -> ExpenseEventPublic:
    project_id: str | None = None
    if event.project_id is not None:
        project = db.query(Project).filter(Project.id == event.project_id).first()
        project_id = project.project_id if project else None
    return ExpenseEventPublic(
        event_id=event.event_id,
        profit_month_id=event.profit_month_id,
        project_id=project_id,
        amount_micro_usdc=event.amount_micro_usdc,
        tx_hash=event.tx_hash,
        category=event.category,
        idempotency_key=event.idempotency_key,
        evidence_url=event.evidence_url,
        created_at=event.created_at,
    )
