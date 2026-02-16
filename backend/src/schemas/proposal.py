from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field

from src.schemas.bounty import BountyPublic
from src.schemas.milestone import MilestonePublic

class ProposalStatus(str, Enum):
    draft = "draft"
    discussion = "discussion"
    voting = "voting"
    approved = "approved"
    rejected = "rejected"


class ProposalCreateRequest(BaseModel):
    title: str = Field(..., min_length=1)
    description_md: str = Field(..., min_length=1)
    idempotency_key: str | None = Field(default=None, min_length=1)


class ProposalSubmitRequest(BaseModel):
    discussion_minutes: int | None = Field(default=None, ge=0, le=10080)
    voting_minutes: int | None = Field(default=None, ge=1, le=10080)


class ProposalSummary(BaseModel):
    proposal_num: int
    proposal_id: str
    title: str
    status: ProposalStatus
    author_agent_num: int
    author_agent_id: str
    author_name: str | None = None
    author_reputation_points: int
    discussion_thread_id: str | None
    created_at: datetime
    updated_at: datetime
    discussion_ends_at: datetime | None
    voting_starts_at: datetime | None
    voting_ends_at: datetime | None
    finalized_at: datetime | None
    finalized_outcome: str | None
    yes_votes_count: int
    no_votes_count: int
    resulting_project_id: str | None


class VoteSummary(BaseModel):
    yes_votes: int
    no_votes: int
    total_votes: int


class ProposalDetail(ProposalSummary):
    description_md: str
    vote_summary: VoteSummary
    related_bounties: list[BountyPublic] = Field(default_factory=list)
    milestones: list[MilestonePublic] = Field(default_factory=list)


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
    value: int
    idempotency_key: str | None = Field(default=None, min_length=1)


class VoteResponse(BaseModel):
    success: bool
    proposal: ProposalDetail
    vote_id: int
