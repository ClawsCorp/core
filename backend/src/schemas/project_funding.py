from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class ProjectFundingRoundCreateRequest(BaseModel):
    idempotency_key: str = Field(..., min_length=1)
    title: str | None = None
    cap_micro_usdc: int | None = Field(default=None, ge=0)


class ProjectFundingRoundPublic(BaseModel):
    round_id: str
    project_id: str
    title: str | None
    status: str
    cap_micro_usdc: int | None
    opened_at: datetime
    closed_at: datetime | None
    created_at: datetime


class ProjectFundingRoundCreateResponse(BaseModel):
    success: bool
    data: ProjectFundingRoundPublic | None = None
    blocked_reason: str | None = None


class ProjectFundingRoundCloseRequest(BaseModel):
    idempotency_key: str = Field(..., min_length=1)


class ProjectFundingContributor(BaseModel):
    address: str
    amount_micro_usdc: int


class ProjectFundingSummary(BaseModel):
    project_id: str
    open_round: ProjectFundingRoundPublic | None
    open_round_raised_micro_usdc: int
    total_raised_micro_usdc: int
    contributors: list[ProjectFundingContributor]
    contributors_total_count: int
    contributors_data_source: str = "observed_transfers"
    unattributed_micro_usdc: int = 0
    last_deposit_at: datetime | None


class ProjectFundingSummaryResponse(BaseModel):
    success: bool
    data: ProjectFundingSummary
