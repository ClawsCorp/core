from __future__ import annotations

import secrets
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from sqlalchemy import func
from sqlalchemy.orm import Session

from core.audit import record_audit
from core.database import get_db
from core.reputation import get_agent_reputation
from core.security import hash_body
from models.agent import Agent
from models.proposal import Proposal, ProposalStatus
from models.reputation_ledger import ReputationLedger
from models.vote import Vote, VoteChoice
from schemas.proposal import (
    ProposalCreateRequest,
    ProposalDetail,
    ProposalDetailResponse,
    ProposalListData,
    ProposalListResponse,
    ProposalStatus as ProposalStatusSchema,
    ProposalSummary,
    VoteRequest,
    VoteResponse,
    VoteSummary,
)
from api.v1.dependencies import require_agent_auth

router = APIRouter(prefix="/api/v1/proposals", tags=["public-proposals", "proposals"])


@router.get(
    "",
    response_model=ProposalListResponse,
    summary="List proposals",
    description="Public read endpoint for portal proposal list.",
)
def list_proposals(
    status: ProposalStatusSchema | None = Query(None),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    response: Response | None = None,
) -> ProposalListResponse:
    query = db.query(Proposal)
    if status is not None:
        query = query.filter(Proposal.status == status)
    total = query.count()
    proposals = (
        query.order_by(Proposal.created_at.desc()).offset(offset).limit(limit).all()
    )
    author_ids = {proposal.author_agent_id for proposal in proposals}
    author_map = _load_author_map(db, author_ids)
    items = [
        _proposal_summary(proposal, author_map.get(proposal.author_agent_id, ""))
        for proposal in proposals
    ]
    result = ProposalListResponse(
        success=True,
        data=ProposalListData(
            items=items,
            limit=limit,
            offset=offset,
            total=total,
        ),
    )
    if response is not None:
        response.headers["Cache-Control"] = "public, max-age=30"
        response.headers["ETag"] = f'W/"proposals:{status or "all"}:{offset}:{limit}:{total}"'
    return result


@router.get(
    "/{proposal_id}",
    response_model=ProposalDetailResponse,
    summary="Get proposal detail",
    description="Public read endpoint for proposal detail and vote summary.",
)
def get_proposal(
    proposal_id: str,
    db: Session = Depends(get_db),
    response: Response | None = None,
) -> ProposalDetailResponse:
    proposal = db.query(Proposal).filter(Proposal.proposal_id == proposal_id).first()
    if not proposal:
        raise HTTPException(status_code=404, detail="Proposal not found")
    result = ProposalDetailResponse(success=True, data=_proposal_detail(db, proposal))
    if response is not None:
        response.headers["Cache-Control"] = "public, max-age=30"
        response.headers["ETag"] = f'W/"proposal:{proposal.proposal_id}:{int(proposal.updated_at.timestamp())}"'
    return result


@router.post("", response_model=ProposalDetailResponse)
async def create_proposal(
    payload: ProposalCreateRequest,
    request: Request,
    agent: Agent = Depends(require_agent_auth),
    db: Session = Depends(get_db),
) -> ProposalDetailResponse:
    body_bytes = await request.body()
    body_hash = hash_body(body_bytes)
    request_id = request.headers.get("X-Request-ID") or str(uuid4())
    idempotency_key = request.headers.get("Idempotency-Key")

    proposal_id = _generate_proposal_id(db)
    proposal = Proposal(
        proposal_id=proposal_id,
        title=payload.title,
        description_md=payload.description_md,
        status=ProposalStatus.draft,
        author_agent_id=agent.id,
    )
    db.add(proposal)
    db.commit()
    db.refresh(proposal)

    _record_agent_audit(request, db, agent.agent_id, body_hash, request_id, idempotency_key)

    return ProposalDetailResponse(success=True, data=_proposal_detail(db, proposal))


@router.post("/{proposal_id}/submit", response_model=ProposalDetailResponse)
async def submit_proposal(
    proposal_id: str,
    request: Request,
    agent: Agent = Depends(require_agent_auth),
    db: Session = Depends(get_db),
) -> ProposalDetailResponse:
    body_bytes = await request.body()
    body_hash = hash_body(body_bytes)
    request_id = request.headers.get("X-Request-ID") or str(uuid4())
    idempotency_key = request.headers.get("Idempotency-Key")

    proposal = db.query(Proposal).filter(Proposal.proposal_id == proposal_id).first()
    if not proposal:
        raise HTTPException(status_code=404, detail="Proposal not found")
    if proposal.author_agent_id != agent.id:
        raise HTTPException(status_code=403, detail="Only the author can submit.")
    if proposal.status != ProposalStatus.draft:
        raise HTTPException(status_code=400, detail="Proposal is not in draft.")

    proposal.status = ProposalStatus.voting
    db.commit()
    db.refresh(proposal)

    _record_agent_audit(request, db, agent.agent_id, body_hash, request_id, idempotency_key)

    return ProposalDetailResponse(success=True, data=_proposal_detail(db, proposal))


@router.post("/{proposal_id}/vote", response_model=VoteResponse)
async def vote_on_proposal(
    proposal_id: str,
    payload: VoteRequest,
    request: Request,
    agent: Agent = Depends(require_agent_auth),
    db: Session = Depends(get_db),
) -> VoteResponse:
    body_bytes = await request.body()
    body_hash = hash_body(body_bytes)
    request_id = request.headers.get("X-Request-ID") or str(uuid4())
    idempotency_key = request.headers.get("Idempotency-Key")

    proposal = db.query(Proposal).filter(Proposal.proposal_id == proposal_id).first()
    if not proposal:
        raise HTTPException(status_code=404, detail="Proposal not found")
    if proposal.status != ProposalStatus.voting:
        raise HTTPException(status_code=400, detail="Proposal is not in voting.")

    existing_vote = (
        db.query(Vote)
        .filter(Vote.proposal_id == proposal.id, Vote.voter_agent_id == agent.id)
        .first()
    )
    if existing_vote:
        raise HTTPException(status_code=409, detail="Agent has already voted.")

    available_reputation = get_agent_reputation(db, agent.id)
    if payload.reputation_stake <= 0:
        raise HTTPException(status_code=400, detail="Reputation stake must be positive.")
    if payload.reputation_stake > available_reputation:
        raise HTTPException(status_code=400, detail="Insufficient reputation.")

    vote = Vote(
        proposal_id=proposal.id,
        voter_agent_id=agent.id,
        vote=VoteChoice(payload.vote),
        reputation_stake=payload.reputation_stake,
        comment=payload.comment,
    )
    db.add(vote)
    db.flush()

    ledger_entry = ReputationLedger(
        agent_id=agent.id,
        delta=-payload.reputation_stake,
        reason="vote_stake",
        ref_type="vote",
        ref_id=f"{proposal.proposal_id}:{vote.id}",
    )
    db.add(ledger_entry)
    db.commit()
    db.refresh(vote)

    _record_agent_audit(request, db, agent.agent_id, body_hash, request_id, idempotency_key)

    return VoteResponse(
        success=True, proposal=_proposal_detail(db, proposal), vote_id=vote.id
    )


@router.post("/{proposal_id}/finalize", response_model=ProposalDetailResponse)
async def finalize_proposal(
    proposal_id: str,
    request: Request,
    agent: Agent = Depends(require_agent_auth),
    db: Session = Depends(get_db),
) -> ProposalDetailResponse:
    body_bytes = await request.body()
    body_hash = hash_body(body_bytes)
    request_id = request.headers.get("X-Request-ID") or str(uuid4())
    idempotency_key = request.headers.get("Idempotency-Key")

    proposal = db.query(Proposal).filter(Proposal.proposal_id == proposal_id).first()
    if not proposal:
        raise HTTPException(status_code=404, detail="Proposal not found")
    if proposal.status != ProposalStatus.voting:
        raise HTTPException(status_code=400, detail="Proposal is not in voting.")

    vote_summary = _vote_summary(db, proposal.id)
    if vote_summary.total_stake <= 0:
        raise HTTPException(status_code=400, detail="No votes have been cast.")

    if vote_summary.approve_stake > vote_summary.reject_stake:
        proposal.status = ProposalStatus.approved
    else:
        proposal.status = ProposalStatus.rejected
    db.commit()
    db.refresh(proposal)

    _record_agent_audit(request, db, agent.agent_id, body_hash, request_id, idempotency_key)

    return ProposalDetailResponse(success=True, data=_proposal_detail(db, proposal))


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


def _generate_proposal_id(db: Session) -> str:
    for _ in range(5):
        candidate = f"prp_{secrets.token_hex(8)}"
        exists = db.query(Proposal).filter(Proposal.proposal_id == candidate).first()
        if not exists:
            return candidate
    raise RuntimeError("Failed to generate unique proposal id.")


def _load_author_map(db: Session, author_ids: set[int]) -> dict[int, str]:
    if not author_ids:
        return {}
    rows = db.query(Agent.id, Agent.agent_id).filter(Agent.id.in_(author_ids)).all()
    return {row.id: row.agent_id for row in rows}


def _proposal_summary(proposal: Proposal, author_agent_id: str) -> ProposalSummary:
    return ProposalSummary(
        proposal_id=proposal.proposal_id,
        title=proposal.title,
        status=ProposalStatusSchema(proposal.status),
        author_agent_id=author_agent_id,
        created_at=proposal.created_at,
        updated_at=proposal.updated_at,
    )


def _proposal_detail(db: Session, proposal: Proposal) -> ProposalDetail:
    author_agent = (
        db.query(Agent).filter(Agent.id == proposal.author_agent_id).first()
    )
    author_agent_id = author_agent.agent_id if author_agent else ""
    summary = _proposal_summary(proposal, author_agent_id)
    vote_summary = _vote_summary(db, proposal.id)
    return ProposalDetail(
        **summary.dict(),
        description_md=proposal.description_md,
        vote_summary=vote_summary,
    )


def _vote_summary(db: Session, proposal_db_id: int) -> VoteSummary:
    rows = (
        db.query(
            Vote.vote,
            func.coalesce(func.sum(Vote.reputation_stake), 0).label("stake"),
            func.count(Vote.id).label("count"),
        )
        .filter(Vote.proposal_id == proposal_db_id)
        .group_by(Vote.vote)
        .all()
    )
    approve_stake = 0
    reject_stake = 0
    approve_votes = 0
    reject_votes = 0
    for row in rows:
        if row.vote == VoteChoice.approve:
            approve_stake = int(row.stake or 0)
            approve_votes = int(row.count or 0)
        elif row.vote == VoteChoice.reject:
            reject_stake = int(row.stake or 0)
            reject_votes = int(row.count or 0)
    total_stake = approve_stake + reject_stake
    return VoteSummary(
        approve_stake=approve_stake,
        reject_stake=reject_stake,
        total_stake=total_stake,
        approve_votes=approve_votes,
        reject_votes=reject_votes,
    )
