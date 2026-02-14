from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class ProjectSpendPolicyPublic(BaseModel):
    project_id: str
    per_bounty_cap_micro_usdc: int | None
    per_day_cap_micro_usdc: int | None
    per_month_cap_micro_usdc: int | None
    created_at: datetime
    updated_at: datetime


class ProjectSpendPolicyUpsertRequest(BaseModel):
    per_bounty_cap_micro_usdc: int | None = Field(default=None, ge=0)
    per_day_cap_micro_usdc: int | None = Field(default=None, ge=0)
    per_month_cap_micro_usdc: int | None = Field(default=None, ge=0)


class ProjectSpendPolicyResponse(BaseModel):
    success: bool
    data: ProjectSpendPolicyPublic | None

