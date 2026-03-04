# SPDX-License-Identifier: BSL-1.1

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class StakerItem(BaseModel):
    address: str
    stake_micro_usdc: int = Field(..., ge=0)


class StakersSummaryData(BaseModel):
    funding_pool_address: str | None
    stakers_count: int = Field(..., ge=0)
    total_staked_micro_usdc: int = Field(..., ge=0)
    top: list[StakerItem]
    blocked_reason: str | None


class StakersSummaryResponse(BaseModel):
    success: bool
    data: StakersSummaryData


class PlatformInvestorReputationSyncData(BaseModel):
    funding_pool_address: str
    transfers_seen: int = Field(..., ge=0)
    reputation_events_created: int = Field(..., ge=0)
    recognized_investor_transfers: int = Field(..., ge=0)


class PlatformInvestorReputationSyncResponse(BaseModel):
    success: bool
    data: PlatformInvestorReputationSyncData | None = None
    blocked_reason: str | None = None


class PlatformFundingRoundCreateRequest(BaseModel):
    idempotency_key: str = Field(..., min_length=1)
    title: str | None = None
    cap_micro_usdc: int | None = Field(default=None, ge=0)


class PlatformFundingRoundCloseRequest(BaseModel):
    idempotency_key: str = Field(..., min_length=1)


class PlatformFundingRoundPublic(BaseModel):
    round_id: str
    title: str | None
    status: str
    cap_micro_usdc: int | None
    opened_at: datetime
    closed_at: datetime | None
    created_at: datetime


class PlatformFundingRoundCreateResponse(BaseModel):
    success: bool
    data: PlatformFundingRoundPublic | None = None
    blocked_reason: str | None = None


class PlatformFundingContributor(BaseModel):
    address: str
    amount_micro_usdc: int = Field(..., ge=0)


class PlatformFundingSummaryData(BaseModel):
    funding_pool_address: str | None
    open_round: PlatformFundingRoundPublic | None
    open_round_raised_micro_usdc: int = Field(..., ge=0)
    total_raised_micro_usdc: int = Field(..., ge=0)
    contributors: list[PlatformFundingContributor]
    contributors_total_count: int = Field(..., ge=0)
    contributors_data_source: str = "observed_transfers"
    unattributed_micro_usdc: int = Field(default=0, ge=0)
    last_deposit_at: datetime | None
    blocked_reason: str | None = None


class PlatformFundingSummaryResponse(BaseModel):
    success: bool
    data: PlatformFundingSummaryData


class PlatformFundingSyncData(BaseModel):
    funding_pool_address: str
    transfers_seen: int = Field(..., ge=0)
    deposits_inserted: int = Field(..., ge=0)
    reputation_events_created: int = Field(default=0, ge=0)
    recognized_investor_transfers: int = Field(default=0, ge=0)
    open_round_id: str | None = None


class PlatformFundingSyncResponse(BaseModel):
    success: bool
    data: PlatformFundingSyncData | None = None
    blocked_reason: str | None = None
