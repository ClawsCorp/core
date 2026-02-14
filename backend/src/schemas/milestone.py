# SPDX-License-Identifier: BSL-1.1

from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field


class MilestoneStatus(str, Enum):
    planned = "planned"
    in_progress = "in_progress"
    done = "done"


class MilestonePublic(BaseModel):
    milestone_id: str
    proposal_id: str
    title: str
    description_md: str | None
    status: MilestoneStatus
    priority: str | None = None
    deadline_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class MilestoneListData(BaseModel):
    items: list[MilestonePublic]


class MilestoneListResponse(BaseModel):
    success: bool
    data: MilestoneListData


class MarketplaceGenerateRequest(BaseModel):
    idempotency_key: str | None = Field(default=None, min_length=1)


class MarketplaceGenerateData(BaseModel):
    proposal_id: str
    created_milestones_count: int
    created_bounties_count: int


class MarketplaceGenerateResponse(BaseModel):
    success: bool
    data: MarketplaceGenerateData

