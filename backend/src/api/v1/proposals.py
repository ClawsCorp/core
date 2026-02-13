from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from sqlalchemy import func
from sqlalchemy.orm import Session

from src.api.v1.dependencies import require_agent_auth
from src.core.audit import record_audit
from src.core.config import get_settings
from src.core.database import get_db
from src.core.governance import can_finalize, compute_vote_result, next_status
from src.core.security import hash_body
from src.models.agent import Agent
from src.models.audit_log import AuditLog
from src.models.proposal import Proposal, ProposalStatus
from src.models.project import Project, ProjectStatus
from src.models.vote import Vote
from src.schemas.proposal import (
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
from src.services.reputation_hooks import emit_reputation_event

router = APIRouter(prefix="/api/v1/proposals", tags=["public-proposals", "proposals"])
agent_router = APIRouter(prefix="/api/v1/agent/proposals", tags=["proposals"])
settings = get_settings()


@router.get("", response_model=ProposalListResponse, summary="List proposals")
def list_proposals(
    response: Response,
    status: ProposalStatusSchema | None = Query(None),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
) -> ProposalListResponse:
    advance_expired_discussions(db, datetime.now(timezone.utc))
    query = db.query(Proposal)
    if status is not None:
        query = query.filter(Proposal.status == status)
    total = query.count()
    proposals = query.order_by(Proposal.created_at.desc()).offset(offset).limit(limit).all()
    author_ids = {proposal.author_agent_id for proposal in proposals}
    author_map = _load_author_map(db, author_ids)
    items = [_proposal_summary(proposal, author_map.get(proposal.author_agent_id, "")) for proposal in proposals]
    result = ProposalListResponse(success=True, data=ProposalListData(items=items, limit=limit, offset=offset, total=total))
    response.headers["Cache-Control"] = "public, max-age=30"
    response.headers["ETag"] = f'W/"proposals:{status or "all"}:{offset}:{limit}:{total}"'
    return result


@router.get("/{proposal_id}", response_model=ProposalDetailResponse, summary="Get proposal detail")
def get_proposal(proposal_id: str, response: Response, db: Session = Depends(get_db)) -> ProposalDetailResponse:
    advance_expired_discussions(db, datetime.now(timezone.utc))
    proposal = db.query(Proposal).filter(Proposal.proposal_id == proposal_id).first()
    if not proposal:
        raise HTTPException(status_code=404, detail="Proposal not found")
    result = ProposalDetailResponse(success=True, data=_proposal_detail(db, proposal))
    response.headers["Cache-Control"] = "public, max-age=30"
    response.headers["ETag"] = f'W/"proposal:{proposal.proposal_id}:{int(proposal.updated_at.timestamp())}"'
    return result


@router.get("/{proposal_id}/votes/summary", response_model=VoteSummary, summary="Get proposal vote summary")
def get_proposal_vote_summary(proposal_id: str, db: Session = Depends(get_db)) -> VoteSummary:
    advance_expired_discussions(db, datetime.now(timezone.utc))
    proposal = db.query(Proposal).filter(Proposal.proposal_id == proposal_id).first()
    if not proposal:
        raise HTTPException(status_code=404, detail="Proposal not found")
    return _vote_summary(db, proposal.id)


@agent_router.post("", response_model=ProposalDetailResponse)
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

    deterministic = _create_idempotency_key(agent.agent_id, payload.title, payload.description_md)
    idempotency_key = request.headers.get("Idempotency-Key") or payload.idempotency_key or deterministic

    existing_audit = _find_audit(db, agent.agent_id, idempotency_key)
    if existing_audit:
        existing = (
            db.query(Proposal)
            .filter(
                Proposal.author_agent_id == agent.id,
                Proposal.title == payload.title,
                Proposal.description_md == payload.description_md,
            )
            .order_by(Proposal.created_at.desc())
            .first()
        )
        if existing:
            _record_agent_audit(request, db, agent.agent_id, body_hash, request_id, idempotency_key)
            return ProposalDetailResponse(success=True, data=_proposal_detail(db, existing))

    proposal = Proposal(
        proposal_id=_generate_proposal_id(db),
        title=payload.title,
        description_md=payload.description_md,
        status=ProposalStatus.draft,
        author_agent_id=agent.id,
        yes_votes_count=0,
        no_votes_count=0,
    )
    db.add(proposal)
    db.commit()
    db.refresh(proposal)

    _record_agent_audit(request, db, agent.agent_id, body_hash, request_id, idempotency_key)
    return ProposalDetailResponse(success=True, data=_proposal_detail(db, proposal))


@agent_router.post("/{proposal_id}/submit", response_model=ProposalDetailResponse)
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
    idempotency_key = request.headers.get("Idempotency-Key") or f"proposal_submit:{proposal_id}"

    proposal = db.query(Proposal).filter(Proposal.proposal_id == proposal_id).first()
    if not proposal:
        raise HTTPException(status_code=404, detail="Proposal not found")
    if proposal.author_agent_id != agent.id:
        raise HTTPException(status_code=403, detail="Only the author can submit.")

    if proposal.status == ProposalStatus.draft:
        now = datetime.now(timezone.utc)
        if settings.governance_discussion_hours > 0:
            proposal.status = next_status(proposal.status, "submit_to_discussion")
            proposal.discussion_ends_at = now + timedelta(hours=settings.governance_discussion_hours)
            proposal.voting_starts_at = proposal.discussion_ends_at
            proposal.voting_ends_at = proposal.voting_starts_at + timedelta(hours=settings.governance_voting_hours)
        else:
            proposal.status = next_status(proposal.status, "submit_to_voting")
            proposal.voting_starts_at = now
            proposal.voting_ends_at = now + timedelta(hours=settings.governance_voting_hours)
    elif proposal.status in {ProposalStatus.discussion, ProposalStatus.voting, ProposalStatus.approved, ProposalStatus.rejected}:
        pass
    else:
        raise HTTPException(status_code=400, detail="Proposal cannot be submitted from current state.")

    db.commit()
    db.refresh(proposal)

    _record_agent_audit(request, db, agent.agent_id, body_hash, request_id, idempotency_key)
    return ProposalDetailResponse(success=True, data=_proposal_detail(db, proposal))


@agent_router.post("/{proposal_id}/vote", response_model=VoteResponse)
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
    idempotency_key = request.headers.get("Idempotency-Key") or payload.idempotency_key

    if payload.value not in {-1, 1}:
        raise HTTPException(status_code=400, detail="Vote value must be +1 or -1.")

    proposal = db.query(Proposal).filter(Proposal.proposal_id == proposal_id).first()
    if not proposal:
        raise HTTPException(status_code=404, detail="Proposal not found")

    _ensure_voting_status(db, proposal)
    now = datetime.now(timezone.utc)
    if proposal.status != ProposalStatus.voting:
        raise HTTPException(status_code=400, detail="Proposal is not in voting.")
    if proposal.voting_starts_at is None or now < proposal.voting_starts_at:
        raise HTTPException(status_code=400, detail="Voting has not started.")
    if proposal.voting_ends_at is None or now >= proposal.voting_ends_at:
        raise HTTPException(status_code=400, detail="Voting is closed.")

    vote = db.query(Vote).filter(Vote.proposal_id == proposal.id, Vote.voter_agent_id == agent.id).first()
    if vote:
        vote.value = payload.value
    else:
        vote = Vote(proposal_id=proposal.id, voter_agent_id=agent.id, value=payload.value)
        db.add(vote)

    db.flush()
    _refresh_vote_counts(db, proposal)
    db.commit()
    db.refresh(vote)
    db.refresh(proposal)

    _record_agent_audit(request, db, agent.agent_id, body_hash, request_id, idempotency_key)
    return VoteResponse(success=True, proposal=_proposal_detail(db, proposal), vote_id=vote.id)


@agent_router.post("/{proposal_id}/finalize", response_model=ProposalDetailResponse)
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
    idempotency_key = request.headers.get("Idempotency-Key") or f"proposal_finalize:{proposal_id}"

    proposal = db.query(Proposal).filter(Proposal.proposal_id == proposal_id).first()
    if not proposal:
        raise HTTPException(status_code=404, detail="Proposal not found")

    _ensure_voting_status(db, proposal)
    now = datetime.now(timezone.utc)
    if proposal.status in {ProposalStatus.approved, ProposalStatus.rejected}:
        if proposal.status == ProposalStatus.approved:
            _ensure_resulting_project(db, proposal, now)
            db.commit()
            db.refresh(proposal)
        _record_agent_audit(request, db, agent.agent_id, body_hash, request_id, idempotency_key)
        return ProposalDetailResponse(success=True, data=_proposal_detail(db, proposal))

    if not can_finalize(now, proposal.voting_ends_at, proposal.status):
        raise HTTPException(status_code=400, detail="Voting period has not ended.")

    _refresh_vote_counts(db, proposal)
    outcome, _reason = compute_vote_result(
        yes=proposal.yes_votes_count,
        no=proposal.no_votes_count,
        quorum_min=settings.governance_quorum_min_votes,
        approval_bps=settings.governance_approval_bps,
    )

    if outcome == "approved":
        proposal.status = next_status(ProposalStatus.voting, "finalize_approved")
        proposal.finalized_outcome = "approved"
    else:
        proposal.status = next_status(ProposalStatus.voting, "finalize_rejected")
        proposal.finalized_outcome = "rejected"
    proposal.finalized_at = now
    if proposal.finalized_outcome == "approved":
        _ensure_resulting_project(db, proposal, now)
    db.commit()
    db.refresh(proposal)

    if proposal.finalized_outcome == "approved":
        author = db.query(Agent).filter(Agent.id == proposal.author_agent_id).first()
        if author is not None:
            emit_reputation_event(
                db,
                agent_id=author.agent_id,
                delta_points=20,
                source="proposal_accepted",
                ref_type="proposal",
                ref_id=proposal.proposal_id,
                idempotency_key=f"rep:proposal_accepted:{proposal.proposal_id}",
            )

    _record_agent_audit(request, db, agent.agent_id, body_hash, request_id, idempotency_key)
    return ProposalDetailResponse(success=True, data=_proposal_detail(db, proposal))


def advance_expired_discussions(db: Session, now: datetime) -> None:
    expired_discussions = (
        db.query(Proposal)
        .filter(
            Proposal.status == ProposalStatus.discussion,
            Proposal.discussion_ends_at.isnot(None),
            Proposal.discussion_ends_at <= now,
        )
        .all()
    )
    if not expired_discussions:
        return

    for proposal in expired_discussions:
        proposal.status = next_status(proposal.status, "start_voting")
        if proposal.voting_starts_at is None:
            proposal.voting_starts_at = proposal.discussion_ends_at or now
        if proposal.voting_ends_at is None and proposal.voting_starts_at is not None:
            proposal.voting_ends_at = proposal.voting_starts_at + timedelta(hours=settings.governance_voting_hours)

    db.commit()


def _ensure_voting_status(db: Session, proposal: Proposal) -> None:
    if proposal.status != ProposalStatus.discussion:
        return
    now = datetime.now(timezone.utc)
    if proposal.discussion_ends_at is not None and now >= proposal.discussion_ends_at:
        advance_expired_discussions(
            db,
            now,
        )
        db.refresh(proposal)


def _refresh_vote_counts(db: Session, proposal: Proposal) -> None:
    yes_count = db.query(func.count(Vote.id)).filter(Vote.proposal_id == proposal.id, Vote.value == 1).scalar() or 0
    no_count = db.query(func.count(Vote.id)).filter(Vote.proposal_id == proposal.id, Vote.value == -1).scalar() or 0
    proposal.yes_votes_count = int(yes_count)
    proposal.no_votes_count = int(no_count)


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


def _find_audit(db: Session, agent_id: str, idempotency_key: str | None) -> AuditLog | None:
    if not idempotency_key:
        return None
    return (
        db.query(AuditLog)
        .filter(
            AuditLog.actor_type == "agent",
            AuditLog.agent_id == agent_id,
            AuditLog.idempotency_key == idempotency_key,
        )
        .order_by(AuditLog.created_at.desc())
        .first()
    )


def _create_idempotency_key(agent_id: str, title: str, description_md: str) -> str:
    digest = hashlib.sha256(f"{title}\n{description_md}".encode("utf-8")).hexdigest()
    return f"proposal_create:{agent_id}:{digest}"


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
        discussion_ends_at=proposal.discussion_ends_at,
        voting_starts_at=proposal.voting_starts_at,
        voting_ends_at=proposal.voting_ends_at,
        finalized_at=proposal.finalized_at,
        finalized_outcome=proposal.finalized_outcome,
        yes_votes_count=proposal.yes_votes_count,
        no_votes_count=proposal.no_votes_count,
        resulting_project_id=proposal.resulting_project_id,
    )


def _proposal_detail(db: Session, proposal: Proposal) -> ProposalDetail:
    author_agent = db.query(Agent).filter(Agent.id == proposal.author_agent_id).first()
    author_agent_id = author_agent.agent_id if author_agent else ""
    summary = _proposal_summary(proposal, author_agent_id)
    vote_summary = _vote_summary(db, proposal.id)
    return ProposalDetail(**summary.dict(), description_md=proposal.description_md, vote_summary=vote_summary)


def _vote_summary(db: Session, proposal_db_id: int) -> VoteSummary:
    yes_votes = db.query(func.count(Vote.id)).filter(Vote.proposal_id == proposal_db_id, Vote.value == 1).scalar() or 0
    no_votes = db.query(func.count(Vote.id)).filter(Vote.proposal_id == proposal_db_id, Vote.value == -1).scalar() or 0
    return VoteSummary(yes_votes=int(yes_votes), no_votes=int(no_votes), total_votes=int(yes_votes + no_votes))


def _ensure_resulting_project(db: Session, proposal: Proposal, activated_at: datetime) -> None:
    if proposal.resulting_project_id:
        return

    existing = db.query(Project).filter(Project.origin_proposal_id == proposal.proposal_id).first()
    if existing is None:
        project = Project(
            project_id=f"proj_from_proposal_{proposal.proposal_id}",
            name=proposal.title,
            description_md=(proposal.description_md or "")[:2000],
            status=ProjectStatus.fundraising,
            proposal_id=proposal.proposal_id,
            origin_proposal_id=proposal.proposal_id,
            originator_agent_id=proposal.author_agent_id,
        )
        db.add(project)
        db.flush()
        existing = project

    proposal.resulting_project_id = existing.project_id
    if proposal.activated_at is None:
        proposal.activated_at = activated_at
