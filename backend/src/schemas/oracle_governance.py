from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


class OracleProposalFastForwardTarget(str, Enum):
    voting = "voting"
    finalize = "finalize"


class OracleProposalFastForwardRequest(BaseModel):
    target: OracleProposalFastForwardTarget
    voting_minutes: int | None = Field(default=None, ge=1, le=60)


class OracleProposalFastForwardData(BaseModel):
    proposal_id: str
    status: str
    discussion_ends_at: str | None
    voting_starts_at: str | None
    voting_ends_at: str | None


class OracleProposalFastForwardResponse(BaseModel):
    success: bool
    data: OracleProposalFastForwardData

