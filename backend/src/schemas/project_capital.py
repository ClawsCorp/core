from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class ProjectCapitalEventCreateRequest(BaseModel):
    idempotency_key: str = Field(..., min_length=1)
    project_id: str = Field(..., min_length=1)
    delta_micro_usdc: int
    source: str = Field(..., min_length=1)
    profit_month_id: str | None = Field(default=None, min_length=6, max_length=6)
    evidence_tx_hash: str | None = None
    evidence_url: str | None = None


class ProjectCapitalEventPublic(BaseModel):
    event_id: str
    idempotency_key: str
    project_id: str
    delta_micro_usdc: int
    source: str
    profit_month_id: str | None
    evidence_tx_hash: str | None
    evidence_url: str | None
    created_at: datetime


class ProjectCapitalEventDetailResponse(BaseModel):
    success: bool
    data: ProjectCapitalEventPublic


class ProjectCapitalSummary(BaseModel):
    project_id: str
    capital_sum_micro_usdc: int
    events_count: int
    last_event_at: datetime | None


class ProjectCapitalSummaryResponse(BaseModel):
    success: bool
    data: ProjectCapitalSummary


class ProjectCapitalLeaderboardData(BaseModel):
    items: list[ProjectCapitalSummary]
    limit: int
    offset: int
    total: int


class ProjectCapitalLeaderboardResponse(BaseModel):
    success: bool
    data: ProjectCapitalLeaderboardData
