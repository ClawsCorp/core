from __future__ import annotations

import secrets
from datetime import datetime, timezone
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from sqlalchemy.orm import Session

from src.api.v1.dependencies import require_agent_auth, require_oracle_hmac
from src.core.audit import record_audit
from src.core.database import get_db
from src.core.security import hash_body
from src.models.agent import Agent
from src.models.bounty import Bounty, BountyStatus
from src.models.expense_event import ExpenseEvent
from src.models.project import Project
from src.services.reputation_hooks import emit_reputation_event

from src.schemas.bounty import (
    BountyCreateRequest,
    BountyDetailResponse,
    BountyEligibilityRequest,
    BountyEligibilityResponse,
    BountyListData,
    BountyListResponse,
    BountyMarkPaidRequest,
    BountyPublic,
    BountyStatus as BountyStatusSchema,
    BountySubmitRequest,
)

router = APIRouter(prefix="/api/v1/bounties", tags=["public-bounties", "bounties"])

REQUIRED_APPROVALS_MIN = 1
REQUIRED_CHECKS = [
    "backend",
    "frontend",
    "contracts",
    "dependency-review",
    "secrets-scan",
]


@router.get(
    "",
    response_model=BountyListResponse,
    summary="List bounties",
    description="Public read endpoint for portal bounty list.",
)
def list_bounties(
    response: Response,
    status: BountyStatusSchema | None = Query(None),
    project_id: str | None = Query(None),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
) -> BountyListResponse:
    query = db.query(Bounty, Project.project_id, Agent.agent_id).outerjoin(
        Project, Bounty.project_id == Project.id
    ).outerjoin(Agent, Bounty.claimant_agent_id == Agent.id)
    if status is not None:
        query = query.filter(Bounty.status == BountyStatus(status))
    if project_id is not None:
        query = query.filter(Project.project_id == project_id)
    total = query.count()
    rows = (
        query.order_by(Bounty.created_at.desc()).offset(offset).limit(limit).all()
    )
    items = [_bounty_public(row.Bounty, row.project_id, row.agent_id) for row in rows]
    result = BountyListResponse(
        success=True,
        data=BountyListData(items=items, limit=limit, offset=offset, total=total),
    )
    response.headers["Cache-Control"] = "public, max-age=30"
    response.headers["ETag"] = f'W/"bounties:{status or "all"}:{project_id or "all"}:{offset}:{limit}:{total}"'
    return result


@router.get(
    "/{bounty_id}",
    response_model=BountyDetailResponse,
    summary="Get bounty detail",
    description="Public read endpoint for a single bounty status card.",
)
def get_bounty(
    bounty_id: str,
    response: Response,
    db: Session = Depends(get_db),
) -> BountyDetailResponse:
    row = (
        db.query(Bounty, Project.project_id, Agent.agent_id)
        .outerjoin(Project, Bounty.project_id == Project.id)
        .outerjoin(Agent, Bounty.claimant_agent_id == Agent.id)
        .filter(Bounty.bounty_id == bounty_id)
        .first()
    )
    if not row:
        raise HTTPException(status_code=404, detail="Bounty not found")
    result = BountyDetailResponse(
        success=True,
        data=_bounty_public(row.Bounty, row.project_id, row.agent_id),
    )
    response.headers["Cache-Control"] = "public, max-age=30"
    response.headers["ETag"] = f'W/"bounty:{row.Bounty.bounty_id}:{int(row.Bounty.updated_at.timestamp())}"'
    return result


@router.post("", response_model=BountyDetailResponse)
async def create_bounty(
    payload: BountyCreateRequest,
    request: Request,
    _: str = Depends(require_oracle_hmac),
    db: Session = Depends(get_db),
) -> BountyDetailResponse:
    request_id = request.headers.get("X-Request-ID") or str(uuid4())
    idempotency_key = request.headers.get("Idempotency-Key")
    body_hash = request.state.body_hash

    project = db.query(Project).filter(Project.project_id == payload.project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    bounty_id = _generate_bounty_id(db)
    bounty = Bounty(
        bounty_id=bounty_id,
        project_id=project.id,
        title=payload.title,
        description_md=payload.description_md,
        amount_micro_usdc=payload.amount_micro_usdc,
        status=BountyStatus.open,
    )
    db.add(bounty)
    db.commit()
    db.refresh(bounty)

    _record_oracle_audit(request, db, body_hash, request_id, idempotency_key)

    return BountyDetailResponse(
        success=True,
        data=_bounty_public(bounty, project.project_id if project else None, None),
    )


@router.post("/{bounty_id}/claim", response_model=BountyDetailResponse)
async def claim_bounty(
    bounty_id: str,
    request: Request,
    agent: Agent = Depends(require_agent_auth),
    db: Session = Depends(get_db),
) -> BountyDetailResponse:
    body_bytes = await request.body()
    body_hash = hash_body(body_bytes)
    request_id = request.headers.get("X-Request-ID") or str(uuid4())
    idempotency_key = request.headers.get("Idempotency-Key")

    row = (
        db.query(Bounty, Project.project_id)
        .outerjoin(Project, Bounty.project_id == Project.id)
        .filter(Bounty.bounty_id == bounty_id)
        .first()
    )
    if not row:
        raise HTTPException(status_code=404, detail="Bounty not found")
    bounty = row.Bounty
    if bounty.status != BountyStatus.open:
        raise HTTPException(status_code=400, detail="Bounty is not open.")

    bounty.status = BountyStatus.claimed
    bounty.claimant_agent_id = agent.id
    if bounty.claimed_at is None:
        bounty.claimed_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(bounty)

    _record_agent_audit(request, db, agent.agent_id, body_hash, request_id, idempotency_key)

    return BountyDetailResponse(
        success=True,
        data=_bounty_public(bounty, row.project_id, agent.agent_id),
    )


@router.post("/{bounty_id}/submit", response_model=BountyDetailResponse)
async def submit_bounty(
    bounty_id: str,
    payload: BountySubmitRequest,
    request: Request,
    agent: Agent = Depends(require_agent_auth),
    db: Session = Depends(get_db),
) -> BountyDetailResponse:
    body_bytes = await request.body()
    body_hash = hash_body(body_bytes)
    request_id = request.headers.get("X-Request-ID") or str(uuid4())
    idempotency_key = request.headers.get("Idempotency-Key")

    row = (
        db.query(Bounty, Project.project_id, Agent.agent_id)
        .outerjoin(Project, Bounty.project_id == Project.id)
        .outerjoin(Agent, Bounty.claimant_agent_id == Agent.id)
        .filter(Bounty.bounty_id == bounty_id)
        .first()
    )
    if not row:
        raise HTTPException(status_code=404, detail="Bounty not found")
    bounty = row.Bounty
    if bounty.status != BountyStatus.claimed:
        raise HTTPException(status_code=400, detail="Bounty is not claimed.")
    if bounty.claimant_agent_id != agent.id:
        raise HTTPException(status_code=403, detail="Only the claimant can submit.")

    bounty.status = BountyStatus.submitted
    if bounty.submitted_at is None:
        bounty.submitted_at = datetime.now(timezone.utc)
    bounty.pr_url = payload.pr_url
    if payload.merge_sha:
        bounty.merge_sha = payload.merge_sha
    db.commit()
    db.refresh(bounty)

    _record_agent_audit(request, db, agent.agent_id, body_hash, request_id, idempotency_key)

    return BountyDetailResponse(
        success=True,
        data=_bounty_public(bounty, row.project_id, row.agent_id or agent.agent_id),
    )


@router.post("/{bounty_id}/evaluate-eligibility", response_model=BountyEligibilityResponse)
async def evaluate_eligibility(
    bounty_id: str,
    payload: BountyEligibilityRequest,
    request: Request,
    _: str = Depends(require_oracle_hmac),
    db: Session = Depends(get_db),
) -> BountyEligibilityResponse:
    request_id = request.headers.get("X-Request-ID") or str(uuid4())
    idempotency_key = request.headers.get("Idempotency-Key")
    body_hash = request.state.body_hash

    row = (
        db.query(Bounty, Project.project_id, Agent.agent_id)
        .outerjoin(Project, Bounty.project_id == Project.id)
        .outerjoin(Agent, Bounty.claimant_agent_id == Agent.id)
        .filter(Bounty.bounty_id == bounty_id)
        .first()
    )
    if not row:
        raise HTTPException(status_code=404, detail="Bounty not found")
    bounty = row.Bounty
    if bounty.status != BountyStatus.submitted:
        raise HTTPException(status_code=400, detail="Bounty is not submitted.")

    reasons = _evaluate_payload(bounty, payload)
    if not reasons:
        bounty.status = BountyStatus.eligible_for_payout
        bounty.merge_sha = payload.merge_sha
        db.commit()
        db.refresh(bounty)

        if row.agent_id:
            emit_reputation_event(
                db,
                agent_id=row.agent_id,
                delta_points=10,
                source="bounty_eligible",
                ref_type="bounty",
                ref_id=bounty.bounty_id,
                idempotency_key=f"rep:bounty_eligible:{bounty.bounty_id}",
            )
    else:
        db.refresh(bounty)

    _record_oracle_audit(request, db, body_hash, request_id, idempotency_key)

    return BountyEligibilityResponse(
        success=True,
        data=_bounty_public(bounty, row.project_id, row.agent_id),
        reasons=reasons or None,
    )


@router.post("/{bounty_id}/mark-paid", response_model=BountyDetailResponse)
async def mark_paid(
    bounty_id: str,
    payload: BountyMarkPaidRequest,
    request: Request,
    _: str = Depends(require_oracle_hmac),
    db: Session = Depends(get_db),
) -> BountyDetailResponse:
    request_id = request.headers.get("X-Request-ID") or str(uuid4())
    idempotency_key = request.headers.get("Idempotency-Key")
    body_hash = request.state.body_hash

    row = (
        db.query(Bounty, Project.project_id, Agent.agent_id)
        .outerjoin(Project, Bounty.project_id == Project.id)
        .outerjoin(Agent, Bounty.claimant_agent_id == Agent.id)
        .filter(Bounty.bounty_id == bounty_id)
        .first()
    )
    if not row:
        raise HTTPException(status_code=404, detail="Bounty not found")
    bounty = row.Bounty
    if bounty.status not in {BountyStatus.eligible_for_payout, BountyStatus.paid}:
        raise HTTPException(
            status_code=400, detail="Bounty is not eligible for payout."
        )

    if bounty.status != BountyStatus.paid:
        bounty.status = BountyStatus.paid
    bounty.paid_tx_hash = payload.paid_tx_hash or bounty.paid_tx_hash

    _ensure_bounty_paid_expense(db, bounty)
    db.commit()
    db.refresh(bounty)

    if row.agent_id:
        note = f"paid_tx_hash:{payload.paid_tx_hash}" if payload.paid_tx_hash else None
        emit_reputation_event(
            db,
            agent_id=row.agent_id,
            delta_points=5,
            source="bounty_paid",
            ref_type="bounty",
            ref_id=bounty.bounty_id,
            idempotency_key=f"rep:bounty_paid:{bounty.bounty_id}",
            note=note,
        )

    _record_oracle_audit(request, db, body_hash, request_id, idempotency_key)

    return BountyDetailResponse(
        success=True,
        data=_bounty_public(bounty, row.project_id, row.agent_id),
    )


def _evaluate_payload(bounty: Bounty, payload: BountyEligibilityRequest) -> list[str]:
    reasons: list[str] = []
    if not payload.merged:
        reasons.append("pull_request_not_merged")
    if not payload.merge_sha:
        reasons.append("merge_sha_missing")
    if bounty.pr_url and payload.pr_url != bounty.pr_url:
        reasons.append("pr_url_mismatch")
    if not bounty.pr_url:
        reasons.append("pr_url_missing")
    if payload.required_approvals < REQUIRED_APPROVALS_MIN:
        reasons.append("insufficient_approvals")

    checks_by_name = {check.name: check.status for check in payload.required_checks}
    for required_name in REQUIRED_CHECKS:
        if required_name not in checks_by_name:
            reasons.append(f"missing_check:{required_name}")
            continue
        if checks_by_name[required_name] != "success":
            reasons.append(f"check_not_success:{required_name}")

    return reasons


def _record_oracle_audit(
    request: Request,
    db: Session,
    body_hash: str,
    request_id: str,
    idempotency_key: str | None,
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


def _record_agent_audit(
    request: Request,
    db: Session,
    agent_id: str,
    body_hash: str,
    request_id: str,
    idempotency_key: str | None,
) -> None:
    signature_status = getattr(request.state, "signature_status", "none")
    record_audit(
        db,
        actor_type="agent",
        agent_id=agent_id,
        method=request.method,
        path=request.url.path,
        idempotency_key=idempotency_key,
        body_hash=body_hash,
        signature_status=signature_status,
        request_id=request_id,
    )


def _generate_bounty_id(db: Session) -> str:
    for _ in range(5):
        candidate = f"bty_{secrets.token_hex(8)}"
        exists = db.query(Bounty).filter(Bounty.bounty_id == candidate).first()
        if not exists:
            return candidate
    raise RuntimeError("Failed to generate unique bounty id.")


def _bounty_public(
    bounty: Bounty,
    project_id: str | None,
    claimant_agent_id: str | None,
) -> BountyPublic:
    return BountyPublic(
        bounty_id=bounty.bounty_id,
        project_id=project_id,
        title=bounty.title,
        description_md=bounty.description_md,
        amount_micro_usdc=bounty.amount_micro_usdc,
        status=BountyStatusSchema(bounty.status),
        claimant_agent_id=claimant_agent_id,
        claimed_at=bounty.claimed_at,
        submitted_at=bounty.submitted_at,
        pr_url=bounty.pr_url,
        merge_sha=bounty.merge_sha,
        paid_tx_hash=bounty.paid_tx_hash,
        created_at=bounty.created_at,
        updated_at=bounty.updated_at,
    )


def _ensure_bounty_paid_expense(db: Session, bounty: Bounty) -> ExpenseEvent:
    idempotency_key = f"expense:bounty_paid:{bounty.bounty_id}"
    existing = db.query(ExpenseEvent).filter(ExpenseEvent.idempotency_key == idempotency_key).first()
    if existing is not None:
        return existing

    profit_month_id = datetime.now(timezone.utc).strftime("%Y%m")
    category = "project_bounty_payout" if bounty.project_id is not None else "platform_bounty_payout"
    event = ExpenseEvent(
        event_id=_generate_expense_event_id(db),
        profit_month_id=profit_month_id,
        project_id=bounty.project_id,
        amount_micro_usdc=bounty.amount_micro_usdc,
        tx_hash=bounty.paid_tx_hash,
        category=category,
        idempotency_key=idempotency_key,
        evidence_url=None,
    )
    db.add(event)
    db.flush()
    return event


def _generate_expense_event_id(db: Session) -> str:
    for _ in range(5):
        candidate = f"exp_{secrets.token_hex(8)}"
        exists = db.query(ExpenseEvent).filter(ExpenseEvent.event_id == candidate).first()
        if not exists:
            return candidate
    raise RuntimeError("Failed to generate unique expense event id.")
