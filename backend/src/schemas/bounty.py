from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field


class BountyStatus(str, Enum):
    open = "open"
    claimed = "claimed"
    submitted = "submitted"
    eligible_for_payout = "eligible_for_payout"
    paid = "paid"


class BountyCreateRequest(BaseModel):
    project_id: str = Field(..., min_length=1)
    title: str = Field(..., min_length=1)
    description_md: str | None = None
    amount_micro_usdc: int = Field(..., ge=0)


class BountySubmitRequest(BaseModel):
    pr_url: str = Field(..., min_length=1)
    merge_sha: str | None = None


class RequiredCheck(BaseModel):
    name: str = Field(..., min_length=1)
    status: str = Field(..., min_length=1)


class BountyEligibilityRequest(BaseModel):
    pr_url: str = Field(..., min_length=1)
    merged: bool
    merge_sha: str | None = None
    required_checks: list[RequiredCheck]
    required_approvals: int = Field(..., ge=0)


class BountyMarkPaidRequest(BaseModel):
    paid_tx_hash: str = Field(..., min_length=1)


class BountyPublic(BaseModel):
    bounty_id: str
    project_id: str | None
    title: str
    description_md: str | None
    amount_micro_usdc: int
    status: BountyStatus
    claimant_agent_id: str | None
    claimed_at: datetime | None
    submitted_at: datetime | None
    pr_url: str | None
    merge_sha: str | None
    paid_tx_hash: str | None
    created_at: datetime
    updated_at: datetime


class BountyListData(BaseModel):
    items: list[BountyPublic]
    limit: int
    offset: int
    total: int


class BountyListResponse(BaseModel):
    success: bool
    data: BountyListData


class BountyDetailResponse(BaseModel):
    success: bool
    data: BountyPublic


class BountyEligibilityResponse(BaseModel):
    success: bool
    data: BountyPublic
    reasons: list[str] | None = None
