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


class BountyFundingSource(str, Enum):
    project_capital = "project_capital"
    project_revenue = "project_revenue"
    platform_treasury = "platform_treasury"


class BountyCreateRequest(BaseModel):
    project_id: str = Field(..., min_length=1)
    title: str = Field(..., min_length=1)
    description_md: str | None = None
    amount_micro_usdc: int = Field(..., ge=0)

class BountyAgentCreateRequest(BaseModel):
    project_id: str | None = None
    funding_source: BountyFundingSource | None = None
    origin_proposal_id: str | None = None
    title: str = Field(..., min_length=1)
    description_md: str | None = None
    amount_micro_usdc: int = Field(..., ge=0)
    priority: str | None = None
    deadline_at: datetime | None = None
    idempotency_key: str | None = None


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


class BountyMarkPaidBlockedReason(str, Enum):
    insufficient_project_capital = "insufficient_project_capital"
    project_capital_reconciliation_missing = "project_capital_reconciliation_missing"
    project_capital_not_reconciled = "project_capital_not_reconciled"
    project_capital_reconciliation_stale = "project_capital_reconciliation_stale"
    insufficient_project_revenue = "insufficient_project_revenue"
    project_revenue_reconciliation_missing = "project_revenue_reconciliation_missing"
    project_revenue_not_reconciled = "project_revenue_not_reconciled"
    project_revenue_reconciliation_stale = "project_revenue_reconciliation_stale"


class BountyPublic(BaseModel):
    bounty_id: str
    project_id: str | None
    origin_proposal_id: str | None = None
    funding_source: BountyFundingSource
    title: str
    description_md: str | None
    amount_micro_usdc: int
    priority: str | None = None
    deadline_at: datetime | None = None
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


class BountyMarkPaidResponse(BaseModel):
    success: bool
    data: BountyPublic
    blocked_reason: BountyMarkPaidBlockedReason | None = None


class BountyEligibilityResponse(BaseModel):
    success: bool
    data: BountyPublic
    reasons: list[str] | None = None
