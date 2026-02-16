# SPDX-License-Identifier: BSL-1.1

from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from src.api.v1.dependencies import require_agent_auth
from src.core.audit import record_audit
from src.core.db_utils import insert_or_get_by_unique
from src.core.security import hash_body
from src.models.agent import Agent
from src.models.bounty import Bounty, BountyFundingSource, BountyStatus
from src.models.milestone import Milestone, MilestoneStatus
from src.models.proposal import Proposal
from src.core.database import get_db
from src.schemas.milestone import MarketplaceGenerateRequest, MarketplaceGenerateResponse

router = APIRouter(prefix="/api/v1/agent/marketplace", tags=["agent-marketplace"])


def _generate_milestone_id(db: Session) -> str:
    for _ in range(5):
        candidate = f"mil_{secrets.token_hex(8)}"
        exists = db.query(Milestone).filter(Milestone.milestone_id == candidate).first()
        if not exists:
            return candidate
    raise RuntimeError("Failed to generate unique milestone id")


def _generate_bounty_id(db: Session) -> str:
    for _ in range(5):
        candidate = f"bty_{secrets.token_hex(8)}"
        exists = db.query(Bounty).filter(Bounty.bounty_id == candidate).first()
        if not exists:
            return candidate
    raise RuntimeError("Failed to generate unique bounty id")


def _record_agent_audit(
    request: Request,
    db: Session,
    *,
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
        commit=False,
    )


@router.post(
    "/proposals/{proposal_id}/generate",
    response_model=MarketplaceGenerateResponse,
    summary="Generate milestones and bounties for a proposal (agent)",
    description="MVP marketplace generator: creates deterministic milestone + bounty records linked to proposal.",
)
async def generate_marketplace_items(
    proposal_id: str,
    payload: MarketplaceGenerateRequest,
    request: Request,
    agent: Agent = Depends(require_agent_auth),
    db: Session = Depends(get_db),
) -> MarketplaceGenerateResponse:
    body_bytes = await request.body()
    body_hash = hash_body(body_bytes)
    request_id = request.headers.get("X-Request-ID") or str(uuid4())

    proposal = _find_proposal_by_identifier(db, proposal_id)
    if proposal is None:
        raise HTTPException(status_code=404, detail="Proposal not found")
    # Use canonical public proposal id in deterministic idempotency key so numeric/public
    # route aliases are equivalent for retries.
    generator_key = f"marketplace:proposal:{proposal.proposal_id}:v1"
    idempotency_key = request.headers.get("Idempotency-Key") or payload.idempotency_key or generator_key

    # MVP heuristics: 3 milestones, 1 bounty each (implementation work is usually milestone 2).
    now = datetime.now(timezone.utc)
    default_deadline = now + timedelta(days=7)

    created_milestones = 0
    created_bounties = 0

    milestone_specs = [
        {
            "slug": "spec",
            "title": "Milestone: spec and acceptance criteria",
            "description_md": "Define scope, acceptance criteria, and constraints for the proposal.",
            "priority": "high",
            "deadline_at": default_deadline,
        },
        {
            "slug": "mvp",
            "title": "Milestone: MVP implementation",
            "description_md": "Implement the minimal working version with tests and docs updates.",
            "priority": "high",
            "deadline_at": default_deadline + timedelta(days=7),
        },
        {
            "slug": "deploy",
            "title": "Milestone: deployment + verification",
            "description_md": "Deploy and verify end-to-end flow; ensure fail-closed money paths stay green.",
            "priority": "medium",
            "deadline_at": default_deadline + timedelta(days=14),
        },
    ]

    for spec in milestone_specs:
        midem = f"{generator_key}:milestone:{spec['slug']}"
        milestone = Milestone(
            milestone_id=_generate_milestone_id(db),
            idempotency_key=midem,
            proposal_id=proposal.id,
            title=spec["title"],
            description_md=spec["description_md"],
            status=MilestoneStatus.planned,
            priority=spec["priority"],
            deadline_at=spec["deadline_at"],
        )
        milestone, created = insert_or_get_by_unique(
            db,
            instance=milestone,
            model=Milestone,
            unique_filter={"idempotency_key": midem},
        )
        created_milestones += 1 if created else 0

        # One bounty per milestone in MVP.
        b_idem = f"{generator_key}:bounty:{spec['slug']}"
        bounty = Bounty(
            bounty_id=_generate_bounty_id(db),
            idempotency_key=b_idem,
            project_id=None,
            origin_proposal_id=proposal.proposal_id,
            origin_milestone_id=milestone.milestone_id,
            funding_source=BountyFundingSource.platform_treasury,
            title=spec["title"].replace("Milestone:", "Bounty:"),
            description_md=spec["description_md"],
            amount_micro_usdc=250_000,  # MVP default: 0.25 USDC
            priority=spec["priority"],
            deadline_at=spec["deadline_at"],
            status=BountyStatus.open,
        )
        bounty, b_created = insert_or_get_by_unique(
            db,
            instance=bounty,
            model=Bounty,
            unique_filter={"idempotency_key": b_idem},
        )
        created_bounties += 1 if b_created else 0

    _record_agent_audit(
        request,
        db,
        agent_id=agent.agent_id,
        body_hash=body_hash,
        request_id=request_id,
        idempotency_key=idempotency_key,
    )
    db.commit()

    return MarketplaceGenerateResponse(
        success=True,
        data={
            "proposal_id": proposal.proposal_id,
            "created_milestones_count": created_milestones,
            "created_bounties_count": created_bounties,
        },
    )


def _find_proposal_by_identifier(db: Session, identifier: str) -> Proposal | None:
    if identifier.isdigit():
        return db.query(Proposal).filter(Proposal.id == int(identifier)).first()
    return db.query(Proposal).filter(Proposal.proposal_id == identifier).first()
