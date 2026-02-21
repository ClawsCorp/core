from __future__ import annotations

import secrets
from datetime import datetime, timezone
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from sqlalchemy.orm import Session

from src.api.v1.dependencies import require_agent_auth, require_oracle_hmac
from src.core.audit import record_audit
from src.core.config import get_settings
from src.core.database import get_db
from src.core.db_utils import insert_or_get_by_unique
from src.core.security import hash_body
from src.models.agent import Agent
from src.models.bounty import Bounty, BountyFundingSource, BountyStatus
from src.models.expense_event import ExpenseEvent
from src.models.project_capital_event import ProjectCapitalEvent
from src.models.milestone import Milestone
from src.models.proposal import Proposal
from src.models.project import Project
from src.services.project_capital import (
    get_latest_project_capital_reconciliation,
    get_project_capital_spendable_balance_micro_usdc,
    is_reconciliation_fresh,
)
from src.services.project_revenue import (
    get_latest_project_revenue_reconciliation,
    get_project_revenue_spendable_balance_micro_usdc,
    is_reconciliation_fresh as is_revenue_reconciliation_fresh,
)
from src.services.project_spend_policy import check_spend_allowed
from src.services.reputation_hooks import emit_reputation_event

from src.schemas.bounty import (
    BountyCreateRequest,
    BountyAgentCreateRequest,
    BountyDetailResponse,
    BountyEligibilityRequest,
    BountyEligibilityResponse,
    BountyListData,
    BountyListResponse,
    BountyMarkPaidRequest,
    BountyMarkPaidResponse,
    BountyPublic,
    BountyStatus as BountyStatusSchema,
    BountySubmitRequest,
)

router = APIRouter(prefix="/api/v1/bounties", tags=["public-bounties", "bounties"])
agent_router = APIRouter(prefix="/api/v1/agent/bounties", tags=["agent-bounties"])

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
    origin_proposal_id: str | None = Query(None),
    origin_milestone_id: str | None = Query(None),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
) -> BountyListResponse:
    query = db.query(
        Bounty,
        Project.project_id,
        Agent.id.label("claimant_agent_num"),
        Agent.agent_id,
        Agent.name,
    ).outerjoin(
        Project, Bounty.project_id == Project.id
    ).outerjoin(Agent, Bounty.claimant_agent_id == Agent.id)
    if status is not None:
        query = query.filter(Bounty.status == BountyStatus(status))
    if project_id is not None:
        if project_id.isdigit():
            query = query.filter(Project.id == int(project_id))
        else:
            query = query.filter(Project.project_id == project_id)
    if origin_proposal_id is not None:
        query = query.filter(Bounty.origin_proposal_id == origin_proposal_id)
    if origin_milestone_id is not None:
        query = query.filter(Bounty.origin_milestone_id == origin_milestone_id)
    total = query.count()
    rows = (
        query.order_by(Bounty.created_at.desc()).offset(offset).limit(limit).all()
    )
    items = [
        _bounty_public(
            row.Bounty,
            row.project_id,
            row.claimant_agent_num,
            row.agent_id,
            row.name,
        )
        for row in rows
    ]
    page_max_updated_at = 0
    if rows:
        page_max_updated_at = max(int(row.Bounty.updated_at.timestamp()) for row in rows)
    result = BountyListResponse(
        success=True,
        data=BountyListData(items=items, limit=limit, offset=offset, total=total),
    )
    response.headers["Cache-Control"] = "public, max-age=30"
    response.headers["ETag"] = f'W/"bounties:{status or "all"}:{project_id or "all"}:{origin_proposal_id or "all"}:{origin_milestone_id or "all"}:{offset}:{limit}:{total}:{page_max_updated_at}"'
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
    bounty_ref = _find_bounty_by_identifier(db, bounty_id)
    if not bounty_ref:
        raise HTTPException(status_code=404, detail="Bounty not found")
    row = (
        db.query(
            Bounty,
            Project.project_id,
            Agent.id.label("claimant_agent_num"),
            Agent.agent_id,
            Agent.name,
        )
        .outerjoin(Project, Bounty.project_id == Project.id)
        .outerjoin(Agent, Bounty.claimant_agent_id == Agent.id)
        .filter(Bounty.id == bounty_ref.id)
        .first()
    )
    if not row:
        raise HTTPException(status_code=404, detail="Bounty not found")
    result = BountyDetailResponse(
        success=True,
        data=_bounty_public(
            row.Bounty,
            row.project_id,
            row.claimant_agent_num,
            row.agent_id,
            row.name,
        ),
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
    request_id = request.headers.get("X-Request-Id") or request.headers.get("X-Request-ID") or str(uuid4())
    idempotency_key = request.headers.get("Idempotency-Key")
    body_hash = request.state.body_hash

    project = _find_project_by_identifier(db, payload.project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    bounty_id = _generate_bounty_id(db)
    bounty = Bounty(
        bounty_id=bounty_id,
        project_id=project.id,
        title=payload.title,
        description_md=payload.description_md,
        amount_micro_usdc=payload.amount_micro_usdc,
        funding_source=BountyFundingSource.project_capital,
        status=BountyStatus.open,
    )
    db.add(bounty)
    db.commit()
    db.refresh(bounty)

    _record_oracle_audit(request, db, body_hash, request_id, idempotency_key)

    return BountyDetailResponse(
        success=True,
        data=_bounty_public(bounty, project.project_id if project else None, None, None, None),
    )


@agent_router.post("", response_model=BountyDetailResponse, summary="Create bounty (agent)")
async def create_bounty_agent(
    payload: BountyAgentCreateRequest,
    request: Request,
    agent: Agent = Depends(require_agent_auth),
    db: Session = Depends(get_db),
) -> BountyDetailResponse:
    body_bytes = await request.body()
    body_hash = hash_body(body_bytes)
    request_id = request.headers.get("X-Request-Id") or request.headers.get("X-Request-ID") or str(uuid4())
    idempotency_key = request.headers.get("Idempotency-Key") or payload.idempotency_key

    project: Project | None = None
    if payload.project_id:
        project = _find_project_by_identifier(db, payload.project_id)
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")

    if payload.origin_proposal_id:
        exists = db.query(Proposal).filter(Proposal.proposal_id == payload.origin_proposal_id).first()
        if exists is None:
            raise HTTPException(status_code=404, detail="Proposal not found")

    if payload.origin_milestone_id:
        exists = db.query(Milestone).filter(Milestone.milestone_id == payload.origin_milestone_id).first()
        if exists is None:
            raise HTTPException(status_code=404, detail="Milestone not found")

    requested_source = (
        BountyFundingSource(payload.funding_source.value) if payload.funding_source else None
    )
    if project is None:
        if requested_source is not None and requested_source != BountyFundingSource.platform_treasury:
            raise HTTPException(status_code=400, detail="Platform bounties must use funding_source=platform_treasury")
        funding_source = BountyFundingSource.platform_treasury
    else:
        if requested_source == BountyFundingSource.platform_treasury:
            raise HTTPException(status_code=400, detail="Project bounties cannot use funding_source=platform_treasury")
        funding_source = requested_source or BountyFundingSource.project_capital

    bounty = Bounty(
        bounty_id=_generate_bounty_id(db),
        idempotency_key=idempotency_key,
        project_id=project.id if project else None,
        origin_proposal_id=payload.origin_proposal_id,
        origin_milestone_id=payload.origin_milestone_id,
        funding_source=funding_source,
        title=payload.title,
        description_md=payload.description_md,
        amount_micro_usdc=payload.amount_micro_usdc,
        priority=payload.priority,
        deadline_at=payload.deadline_at,
        status=BountyStatus.open,
    )

    if idempotency_key:
        bounty, _ = insert_or_get_by_unique(
            db,
            instance=bounty,
            model=Bounty,
            unique_filter={"idempotency_key": idempotency_key},
        )
    else:
        db.add(bounty)
        db.flush()

    db.commit()
    db.refresh(bounty)

    _record_agent_audit(request, db, agent.agent_id, body_hash, request_id, idempotency_key)

    project_public_id = project.project_id if project else None
    if project is None and bounty.project_id is not None:
        # In case idempotency returned an existing row, load its project public id.
        project_public_id = (
            db.query(Project.project_id).filter(Project.id == bounty.project_id).scalar()
        )

    return BountyDetailResponse(
        success=True,
        data=_bounty_public(bounty, project_public_id, None, None, None),
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
    request_id = request.headers.get("X-Request-Id") or request.headers.get("X-Request-ID") or str(uuid4())
    idempotency_key = request.headers.get("Idempotency-Key")

    bounty_ref = _find_bounty_by_identifier(db, bounty_id)
    if not bounty_ref:
        raise HTTPException(status_code=404, detail="Bounty not found")
    row = (
        db.query(Bounty, Project.project_id)
        .outerjoin(Project, Bounty.project_id == Project.id)
        .filter(Bounty.id == bounty_ref.id)
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
        data=_bounty_public(bounty, row.project_id, agent.id, agent.agent_id, agent.name),
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
    request_id = request.headers.get("X-Request-Id") or request.headers.get("X-Request-ID") or str(uuid4())
    idempotency_key = request.headers.get("Idempotency-Key")

    bounty_ref = _find_bounty_by_identifier(db, bounty_id)
    if not bounty_ref:
        raise HTTPException(status_code=404, detail="Bounty not found")
    row = (
        db.query(
            Bounty,
            Project.project_id,
            Agent.id.label("claimant_agent_num"),
            Agent.agent_id,
            Agent.name,
        )
        .outerjoin(Project, Bounty.project_id == Project.id)
        .outerjoin(Agent, Bounty.claimant_agent_id == Agent.id)
        .filter(Bounty.id == bounty_ref.id)
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
        data=_bounty_public(
            bounty,
            row.project_id,
            row.claimant_agent_num or agent.id,
            row.agent_id or agent.agent_id,
            row.name or agent.name,
        ),
    )


@router.post("/{bounty_id}/evaluate-eligibility", response_model=BountyEligibilityResponse)
async def evaluate_eligibility(
    bounty_id: str,
    payload: BountyEligibilityRequest,
    request: Request,
    _: str = Depends(require_oracle_hmac),
    db: Session = Depends(get_db),
) -> BountyEligibilityResponse:
    request_id = request.headers.get("X-Request-Id") or request.headers.get("X-Request-ID") or str(uuid4())
    idempotency_key = request.headers.get("Idempotency-Key")
    body_hash = request.state.body_hash

    bounty_ref = _find_bounty_by_identifier(db, bounty_id)
    if not bounty_ref:
        raise HTTPException(status_code=404, detail="Bounty not found")
    row = (
        db.query(
            Bounty,
            Project.project_id,
            Agent.id.label("claimant_agent_num"),
            Agent.agent_id,
            Agent.name,
        )
        .outerjoin(Project, Bounty.project_id == Project.id)
        .outerjoin(Agent, Bounty.claimant_agent_id == Agent.id)
        .filter(Bounty.id == bounty_ref.id)
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
        data=_bounty_public(
            bounty,
            row.project_id,
            row.claimant_agent_num,
            row.agent_id,
            row.name,
        ),
        reasons=reasons or None,
    )


@router.post("/{bounty_id}/mark-paid", response_model=BountyMarkPaidResponse)
async def mark_paid(
    bounty_id: str,
    payload: BountyMarkPaidRequest,
    request: Request,
    _: str = Depends(require_oracle_hmac),
    db: Session = Depends(get_db),
) -> BountyMarkPaidResponse:
    request_id = request.headers.get("X-Request-Id") or request.headers.get("X-Request-ID") or str(uuid4())
    idempotency_key = request.headers.get("Idempotency-Key")
    body_hash = request.state.body_hash

    bounty_ref = _find_bounty_by_identifier(db, bounty_id)
    if not bounty_ref:
        raise HTTPException(status_code=404, detail="Bounty not found")
    row = (
        db.query(
            Bounty,
            Project.project_id,
            Agent.id.label("claimant_agent_num"),
            Agent.agent_id,
            Agent.name,
        )
        .outerjoin(Project, Bounty.project_id == Project.id)
        .outerjoin(Agent, Bounty.claimant_agent_id == Agent.id)
        .filter(Bounty.id == bounty_ref.id)
        .first()
    )
    if not row:
        raise HTTPException(status_code=404, detail="Bounty not found")
    bounty = row.Bounty
    if bounty.status not in {BountyStatus.eligible_for_payout, BountyStatus.paid}:
        raise HTTPException(
            status_code=400, detail="Bounty is not eligible for payout."
        )

    mark_paid_idempotency_key = f"mark_paid:bounty:{bounty.bounty_id}"
    expense_idempotency_key = f"expense:bounty_paid:{bounty.bounty_id}"

    blocked_reason = _ensure_project_capital_reconciliation_gate(db, bounty)
    if blocked_reason is None:
        blocked_reason = _ensure_project_revenue_reconciliation_gate(db, bounty)
    if blocked_reason is None:
        blocked_reason = _ensure_project_spend_policy_gate(db, bounty)
    if blocked_reason is None:
        blocked_reason = _ensure_bounty_paid_capital_outflow(db, bounty, payload.paid_tx_hash)
    if blocked_reason is None:
        blocked_reason = _ensure_bounty_paid_revenue_outflow(db, bounty)
    if blocked_reason is not None:
        compact_error_hint = (
            f"br={blocked_reason};"
            f"b={bounty.bounty_id};"
            f"p={row.project_id or '-'};"
            f"fs={bounty.funding_source.value};"
            f"exp={expense_idempotency_key}"
        )
        _record_oracle_audit(
            request,
            db,
            body_hash,
            request_id,
            idempotency_key or mark_paid_idempotency_key,
            tx_hash=payload.paid_tx_hash,
            error_hint=compact_error_hint,
        )
        return BountyMarkPaidResponse(
            success=False,
            data=_bounty_public(
                bounty,
                row.project_id,
                row.claimant_agent_num,
                row.agent_id,
                row.name,
            ),
            blocked_reason=blocked_reason,
        )

    if bounty.status != BountyStatus.paid:
        bounty.status = BountyStatus.paid
    bounty.paid_tx_hash = payload.paid_tx_hash or bounty.paid_tx_hash

    _ensure_bounty_paid_expense(db, bounty)

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

    _record_oracle_audit(
        request,
        db,
        body_hash,
        request_id,
        idempotency_key or mark_paid_idempotency_key,
        tx_hash=bounty.paid_tx_hash,
        error_hint=None,
        commit=False,
    )
    db.commit()
    db.refresh(bounty)

    return BountyMarkPaidResponse(
        success=True,
        data=_bounty_public(
            bounty,
            row.project_id,
            row.claimant_agent_num,
            row.agent_id,
            row.name,
        ),
        blocked_reason=None,
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
    tx_hash: str | None = None,
    error_hint: str | None = None,
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
        tx_hash=tx_hash,
        error_hint=error_hint,
        commit=commit,
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


def _find_bounty_by_identifier(db: Session, identifier: str) -> Bounty | None:
    if identifier.isdigit():
        return db.query(Bounty).filter(Bounty.id == int(identifier)).first()
    return db.query(Bounty).filter(Bounty.bounty_id == identifier).first()


def _find_project_by_identifier(db: Session, identifier: str) -> Project | None:
    if identifier.isdigit():
        return db.query(Project).filter(Project.id == int(identifier)).first()
    return db.query(Project).filter(Project.project_id == identifier).first()


def _bounty_public(
    bounty: Bounty,
    project_id: str | None,
    claimant_agent_num: int | None,
    claimant_agent_id: str | None,
    claimant_agent_name: str | None,
) -> BountyPublic:
    return BountyPublic(
        bounty_num=bounty.id,
        bounty_id=bounty.bounty_id,
        project_id=project_id,
        origin_proposal_id=bounty.origin_proposal_id,
        origin_milestone_id=bounty.origin_milestone_id,
        funding_source=bounty.funding_source,
        title=bounty.title,
        description_md=bounty.description_md,
        amount_micro_usdc=bounty.amount_micro_usdc,
        priority=bounty.priority,
        deadline_at=bounty.deadline_at,
        status=BountyStatusSchema(bounty.status),
        claimant_agent_num=claimant_agent_num,
        claimant_agent_id=claimant_agent_id,
        claimant_agent_name=claimant_agent_name,
        claimed_at=bounty.claimed_at,
        submitted_at=bounty.submitted_at,
        pr_url=bounty.pr_url,
        merge_sha=bounty.merge_sha,
        paid_tx_hash=bounty.paid_tx_hash,
        created_at=bounty.created_at,
        updated_at=bounty.updated_at,
    )



def _ensure_project_capital_reconciliation_gate(db: Session, bounty: Bounty) -> str | None:
    if bounty.project_id is None:
        return None
    if bounty.funding_source != BountyFundingSource.project_capital:
        return None

    latest_reconciliation = get_latest_project_capital_reconciliation(db, bounty.project_id)
    if latest_reconciliation is None:
        return "project_capital_reconciliation_missing"
    if not latest_reconciliation.ready or latest_reconciliation.delta_micro_usdc != 0:
        return "project_capital_not_reconciled"

    settings = get_settings()
    if not is_reconciliation_fresh(
        latest_reconciliation,
        settings.project_capital_reconciliation_max_age_seconds,
    ):
        return "project_capital_reconciliation_stale"

    return None


def _ensure_project_revenue_reconciliation_gate(db: Session, bounty: Bounty) -> str | None:
    if bounty.project_id is None:
        return None
    if bounty.funding_source != BountyFundingSource.project_revenue:
        return None

    latest_reconciliation = get_latest_project_revenue_reconciliation(db, bounty.project_id)
    if latest_reconciliation is None:
        return "project_revenue_reconciliation_missing"
    if not latest_reconciliation.ready or latest_reconciliation.delta_micro_usdc != 0:
        return "project_revenue_not_reconciled"

    settings = get_settings()
    if not is_revenue_reconciliation_fresh(
        latest_reconciliation,
        settings.project_revenue_reconciliation_max_age_seconds,
    ):
        return "project_revenue_reconciliation_stale"

    return None


def _ensure_bounty_paid_capital_outflow(db: Session, bounty: Bounty, paid_tx_hash: str | None) -> str | None:
    if bounty.project_id is None:
        return None
    if bounty.funding_source != BountyFundingSource.project_capital:
        return None

    idempotency_key = f"cap:bounty_paid:{bounty.bounty_id}"
    balance_micro_usdc = get_project_capital_spendable_balance_micro_usdc(db, bounty.project_id)
    if balance_micro_usdc < bounty.amount_micro_usdc:
        return "insufficient_project_capital"

    event = ProjectCapitalEvent(
        event_id=_generate_project_capital_event_id(db),
        idempotency_key=idempotency_key,
        profit_month_id=datetime.now(timezone.utc).strftime("%Y%m"),
        project_id=bounty.project_id,
        delta_micro_usdc=-bounty.amount_micro_usdc,
        source="bounty_paid",
        evidence_tx_hash=paid_tx_hash,
        evidence_url=f"bounty:{bounty.bounty_id}",
    )
    _, _ = insert_or_get_by_unique(
        db,
        instance=event,
        model=ProjectCapitalEvent,
        unique_filter={"idempotency_key": idempotency_key},
    )
    return None


def _ensure_bounty_paid_revenue_outflow(db: Session, bounty: Bounty) -> str | None:
    if bounty.project_id is None:
        return None
    if bounty.funding_source != BountyFundingSource.project_revenue:
        return None

    balance_micro_usdc = get_project_revenue_spendable_balance_micro_usdc(db, bounty.project_id)
    if balance_micro_usdc < bounty.amount_micro_usdc:
        return "insufficient_project_revenue"
    return None


def _ensure_project_spend_policy_gate(db: Session, bounty: Bounty) -> str | None:
    if bounty.project_id is None:
        return None
    # Policy applies to any project spend (regardless of funding source).
    project = db.query(Project).filter(Project.id == bounty.project_id).first()
    if project is None:
        return "project_not_found"
    profit_month_id = datetime.now(timezone.utc).strftime("%Y%m")
    return check_spend_allowed(
        db,
        project=project,
        profit_month_id=profit_month_id,
        amount_micro_usdc=int(bounty.amount_micro_usdc),
    )

def _ensure_bounty_paid_expense(db: Session, bounty: Bounty) -> ExpenseEvent:
    idempotency_key = f"expense:bounty_paid:{bounty.bounty_id}"
    profit_month_id = datetime.now(timezone.utc).strftime("%Y%m")
    if bounty.project_id is None:
        category = "platform_bounty_payout"
    elif bounty.funding_source == BountyFundingSource.project_capital:
        category = "project_bounty_payout_capital"
    elif bounty.funding_source == BountyFundingSource.project_revenue:
        category = "project_bounty_payout_revenue"
    else:
        category = "project_bounty_payout"
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
    event, _ = insert_or_get_by_unique(
        db,
        instance=event,
        model=ExpenseEvent,
        unique_filter={"idempotency_key": idempotency_key},
    )
    return event


def _generate_project_capital_event_id(db: Session) -> str:
    for _ in range(5):
        candidate = f"pcap_{secrets.token_hex(8)}"
        exists = db.query(ProjectCapitalEvent).filter(ProjectCapitalEvent.event_id == candidate).first()
        if not exists:
            return candidate
    raise RuntimeError("Failed to generate unique project capital event id.")


def _generate_expense_event_id(db: Session) -> str:
    for _ in range(5):
        candidate = f"exp_{secrets.token_hex(8)}"
        exists = db.query(ExpenseEvent).filter(ExpenseEvent.event_id == candidate).first()
        if not exists:
            return candidate
    raise RuntimeError("Failed to generate unique expense event id.")
