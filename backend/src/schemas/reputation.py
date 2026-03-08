from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field
from typing import Literal


class ReputationLedgerEntry(BaseModel):
    agent_id: str
    delta: int
    reason: str
    ref_type: str
    ref_id: str
    created_at: datetime


class ReputationLedgerData(BaseModel):
    items: list[ReputationLedgerEntry]
    limit: int
    offset: int
    total: int


class ReputationLedgerResponse(BaseModel):
    success: bool
    data: ReputationLedgerData


class ReputationEventCreateRequest(BaseModel):
    event_id: str = Field(min_length=1, max_length=64)
    idempotency_key: str = Field(min_length=1, max_length=255)
    agent_id: str = Field(min_length=1, max_length=64)
    delta_points: int
    source: str = Field(min_length=1, max_length=64)
    ref_type: str | None = Field(default=None, max_length=64)
    ref_id: str | None = Field(default=None, max_length=128)
    note: str | None = Field(default=None, max_length=255)


class ReputationEventPublic(BaseModel):
    event_id: str
    idempotency_key: str
    agent_id: str
    delta_points: int
    source: str
    ref_type: str | None
    ref_id: str | None
    note: str | None
    created_at: datetime


class ReputationEventDetailResponse(BaseModel):
    success: bool
    data: ReputationEventPublic


class ReputationEventListData(BaseModel):
    items: list[ReputationEventPublic]
    limit: int
    offset: int
    total: int


class ReputationEventListResponse(BaseModel):
    success: bool
    data: ReputationEventListData


class ReputationSocialSignalCreateRequest(BaseModel):
    agent_id: str = Field(min_length=1, max_length=64)
    idempotency_key: str = Field(min_length=1, max_length=255)
    platform: str = Field(min_length=1, max_length=64)
    signal_url: str | None = Field(default=None, max_length=255)
    account_handle: str | None = Field(default=None, max_length=128)
    note: str | None = Field(default=None, max_length=255)


class ReputationCustomerReferralCreateRequest(BaseModel):
    agent_id: str = Field(min_length=1, max_length=64)
    idempotency_key: str = Field(min_length=1, max_length=255)
    referral_id: str = Field(min_length=1, max_length=128)
    stage: Literal["verified_lead", "paid_conversion"]
    evidence_url: str | None = Field(default=None, max_length=255)
    note: str | None = Field(default=None, max_length=255)


class ReputationAgentSummary(BaseModel):
    agent_num: int
    agent_id: str
    agent_name: str | None = None
    total_points: int
    general_points: int = 0
    governance_points: int = 0
    delivery_points: int = 0
    investor_points: int = 0
    commercial_points: int = 0
    safety_points: int = 0
    events_count: int
    last_event_at: datetime | None


class ReputationAgentSummaryResponse(BaseModel):
    success: bool
    data: ReputationAgentSummary


class ReputationLeaderboardData(BaseModel):
    items: list[ReputationAgentSummary]
    limit: int
    offset: int
    total: int


class ReputationLeaderboardResponse(BaseModel):
    success: bool
    data: ReputationLeaderboardData


class ReputationPolicySourcePublic(BaseModel):
    source: str
    category: str
    description: str
    default_delta_points: int | None
    formula: str | None
    status: str


class ReputationPolicyData(BaseModel):
    categories: list[str]
    investor_project_funding_formula: str
    investor_platform_funding_formula: str
    sources: list[ReputationPolicySourcePublic]


class ReputationPolicyResponse(BaseModel):
    success: bool
    data: ReputationPolicyData
