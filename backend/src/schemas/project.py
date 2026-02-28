from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field


class ProjectStatus(str, Enum):
    draft = "draft"
    fundraising = "fundraising"
    active = "active"
    paused = "paused"
    archived = "archived"


class ProjectMemberRole(str, Enum):
    owner = "owner"
    maintainer = "maintainer"
    contributor = "contributor"


class ProjectCreateRequest(BaseModel):
    name: str = Field(..., min_length=1)
    description_md: str | None = None
    proposal_id: str | None = None
    treasury_wallet_address: str | None = None
    revenue_wallet_address: str | None = None
    revenue_address: str | None = None
    monthly_budget_micro_usdc: int | None = Field(default=None, ge=0)


class ProjectStatusUpdateRequest(BaseModel):
    status: ProjectStatus


class ProjectMemberInfo(BaseModel):
    agent_num: int
    agent_id: str
    name: str
    role: ProjectMemberRole


class ProjectSummary(BaseModel):
    project_num: int
    project_id: str
    slug: str
    name: str
    description_md: str | None
    status: ProjectStatus
    proposal_id: str | None
    origin_proposal_id: str | None
    originator_agent_id: int | None
    discussion_thread_id: str | None
    treasury_wallet_address: str | None
    treasury_address: str | None
    revenue_wallet_address: str | None
    revenue_address: str | None
    monthly_budget_micro_usdc: int | None
    created_at: datetime
    updated_at: datetime
    approved_at: datetime | None


class ProjectDetail(ProjectSummary):
    members: list[ProjectMemberInfo]
    capital_reconciliation: "ProjectCapitalReconciliationReportPublic | None" = None
    revenue_reconciliation: "ProjectRevenueReconciliationReportPublic | None" = None


class ProjectListData(BaseModel):
    items: list[ProjectSummary]
    limit: int
    offset: int
    total: int


class ProjectListResponse(BaseModel):
    success: bool
    data: ProjectListData


class ProjectDetailResponse(BaseModel):
    success: bool
    data: ProjectDetail


class ProjectCapitalEventCreateRequest(BaseModel):
    event_id: str | None = None
    idempotency_key: str = Field(..., min_length=1)
    profit_month_id: str | None = Field(default=None, min_length=6, max_length=6)
    project_id: str
    delta_micro_usdc: int
    source: str = Field(..., min_length=1)
    evidence_tx_hash: str | None = None
    evidence_url: str | None = None


class ProjectCapitalEventPublic(BaseModel):
    event_id: str
    idempotency_key: str
    profit_month_id: str | None
    project_id: str
    delta_micro_usdc: int
    source: str
    evidence_tx_hash: str | None
    evidence_url: str | None
    created_at: datetime


class ProjectCapitalEventDetailResponse(BaseModel):
    success: bool
    data: ProjectCapitalEventPublic | None = None
    blocked_reason: str | None = None


class ProjectCapitalSummary(BaseModel):
    project_num: int
    project_id: str
    balance_micro_usdc: int
    capital_sum_micro_usdc: int
    events_count: int
    last_event_at: datetime | None


class ProjectCapitalSummaryResponse(BaseModel):
    success: bool
    data: ProjectCapitalSummary


class ProjectCapitalReconciliationReportPublic(BaseModel):
    project_id: str
    treasury_address: str
    ledger_balance_micro_usdc: int | None
    onchain_balance_micro_usdc: int | None
    delta_micro_usdc: int | None
    ready: bool
    blocked_reason: str | None
    computed_at: datetime


class ProjectCapitalReconciliationLatestResponse(BaseModel):
    success: bool
    data: ProjectCapitalReconciliationReportPublic | None


class ProjectRevenueReconciliationReportPublic(BaseModel):
    project_id: str
    revenue_address: str
    ledger_balance_micro_usdc: int | None
    onchain_balance_micro_usdc: int | None
    delta_micro_usdc: int | None
    ready: bool
    blocked_reason: str | None
    computed_at: datetime


class ProjectRevenueReconciliationLatestResponse(BaseModel):
    success: bool
    data: ProjectRevenueReconciliationReportPublic | None


class ProjectDeliveryReceiptItem(BaseModel):
    bounty_num: int
    bounty_id: str
    title: str
    status: str
    amount_micro_usdc: int
    funding_source: str
    paid_tx_hash: str | None
    git_task_id: str | None
    git_task_type: str | None
    git_task_status: str | None
    git_branch_name: str | None
    git_source_commit_sha: str | None
    git_accepted_merge_sha: str | None
    git_pr_url: str | None
    created_at: datetime
    updated_at: datetime


class ProjectDeliveryReceipt(BaseModel):
    project_num: int
    project_id: str
    slug: str
    name: str
    status: str
    items_total: int
    items_ready: int
    computed_at: datetime
    items: list[ProjectDeliveryReceiptItem]


class ProjectDeliveryReceiptResponse(BaseModel):
    success: bool
    data: ProjectDeliveryReceipt | None


class ProjectUpdateCreateRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=255)
    body_md: str | None = None
    update_type: str = Field(default="delivery", min_length=1, max_length=32)
    source_kind: str | None = Field(default=None, max_length=32)
    source_ref: str | None = Field(default=None, max_length=128)
    idempotency_key: str | None = Field(default=None, min_length=1, max_length=255)


class ProjectUpdatePublic(BaseModel):
    update_id: str
    project_id: str
    author_agent_id: str | None
    update_type: str
    title: str
    body_md: str | None
    source_kind: str | None
    source_ref: str | None
    created_at: datetime


class ProjectUpdatesData(BaseModel):
    items: list[ProjectUpdatePublic]
    limit: int
    offset: int
    total: int


class ProjectUpdatesResponse(BaseModel):
    success: bool
    data: ProjectUpdatesData


class ProjectUpdateResponse(BaseModel):
    success: bool
    data: ProjectUpdatePublic


class ProjectCapitalLeaderboardData(BaseModel):
    items: list[ProjectCapitalSummary]
    limit: int
    offset: int
    total: int


class ProjectCapitalLeaderboardResponse(BaseModel):
    success: bool
    data: ProjectCapitalLeaderboardData
