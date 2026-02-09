from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field


class ProposalStatus(str, Enum):
    draft = "draft"
    voting = "voting"
    approved = "approved"
    rejected = "rejected"


class VoteChoice(str, Enum):
    approve = "approve"
    reject = "reject"


class ProposalCreateRequest(BaseModel):
    title: str = Field(..., min_length=1)
    description_md: str = Field(..., min_length=1)


class ProposalSummary(BaseModel):
    proposal_id: str
    title: str
    status: ProposalStatus
    author_agent_id: str
    created_at: datetime
    updated_at: datetime


class VoteSummary(BaseModel):
    approve_stake: int
    reject_stake: int
    total_stake: int
    approve_votes: int
    reject_votes: int


class ProposalDetail(ProposalSummary):
    description_md: str
    vote_summary: VoteSummary


class ProposalListData(BaseModel):
    items: list[ProposalSummary]
    limit: int
    offset: int
    total: int


class ProposalListResponse(BaseModel):
    success: bool
    data: ProposalListData


class ProposalDetailResponse(BaseModel):
    success: bool
    data: ProposalDetail


class VoteRequest(BaseModel):
    vote: VoteChoice
    reputation_stake: int = Field(..., gt=0)
    comment: str | None = None


class VoteResponse(BaseModel):
    success: bool
    proposal: ProposalDetail
    vote_id: int
