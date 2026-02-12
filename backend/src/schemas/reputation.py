from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


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


class ReputationAgentSummary(BaseModel):
    agent_id: str
    total_points: int
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
