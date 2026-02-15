# SPDX-License-Identifier: BSL-1.1

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from src.api.v1.dependencies import require_oracle_hmac
from src.core.audit import record_audit
from src.core.database import get_db
from src.models.proposal import Proposal, ProposalStatus
from src.schemas.oracle_governance import (
    OracleProposalFastForwardData,
    OracleProposalFastForwardRequest,
    OracleProposalFastForwardResponse,
    OracleProposalFastForwardTarget,
)

router = APIRouter(prefix="/api/v1/oracle", tags=["oracle-governance"])


def _record_oracle_audit(
    request: Request,
    db: Session,
    *,
    request_id: str,
    idempotency_key: str,
    body_hash: str,
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
        error_hint=error_hint,
        commit=commit,
    )


@router.post(
    "/proposals/{proposal_id}/fast-forward",
    response_model=OracleProposalFastForwardResponse,
    summary="Oracle-only governance helper: fast-forward proposal windows for E2E",
    description="HMAC-protected helper to shorten discussion/voting windows for E2E seeding. Intended for operators/orchestrators only.",
)
async def fast_forward_proposal(
    proposal_id: str,
    payload: OracleProposalFastForwardRequest,
    request: Request,
    _: str = Depends(require_oracle_hmac),
    db: Session = Depends(get_db),
) -> OracleProposalFastForwardResponse:
    request_id = request.headers.get("X-Request-Id") or request.headers.get("X-Request-ID") or str(uuid4())
    body_hash = request.state.body_hash
    idem = request.headers.get("Idempotency-Key") or f"oracle:proposal_fast_forward:{proposal_id}:{payload.target.value}"

    proposal = db.query(Proposal).filter(Proposal.proposal_id == proposal_id).first()
    if proposal is None:
        _record_oracle_audit(request, db, request_id=request_id, idempotency_key=idem, body_hash=body_hash)
        raise HTTPException(status_code=404, detail="Proposal not found")

    now = datetime.now(timezone.utc)
    past = now - timedelta(seconds=2)

    # Always end discussion so voting can begin.
    proposal.discussion_ends_at = past
    if payload.target == OracleProposalFastForwardTarget.voting:
        # Ensure voting is open for a short window so agents can cast votes.
        minutes = int(payload.voting_minutes or 2)
        proposal.status = ProposalStatus.voting
        proposal.voting_starts_at = past
        proposal.voting_ends_at = now + timedelta(minutes=minutes)
    else:
        # Ensure voting is ended so finalize() can run.
        proposal.status = ProposalStatus.voting
        if proposal.voting_starts_at is None:
            proposal.voting_starts_at = past
        proposal.voting_ends_at = past

    _record_oracle_audit(request, db, request_id=request_id, idempotency_key=idem, body_hash=body_hash, commit=False)
    db.commit()
    db.refresh(proposal)

    return OracleProposalFastForwardResponse(
        success=True,
        data=OracleProposalFastForwardData(
            proposal_id=proposal.proposal_id,
            status=str(proposal.status),
            discussion_ends_at=proposal.discussion_ends_at.isoformat() if proposal.discussion_ends_at else None,
            voting_starts_at=proposal.voting_starts_at.isoformat() if proposal.voting_starts_at else None,
            voting_ends_at=proposal.voting_ends_at.isoformat() if proposal.voting_ends_at else None,
        ),
    )

