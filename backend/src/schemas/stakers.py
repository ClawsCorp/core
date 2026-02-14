# SPDX-License-Identifier: BSL-1.1

from __future__ import annotations

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

