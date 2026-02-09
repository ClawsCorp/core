from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field


class ProjectStatus(str, Enum):
    draft = "draft"
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
    monthly_budget_micro_usdc: int | None = Field(default=None, ge=0)


class ProjectStatusUpdateRequest(BaseModel):
    status: ProjectStatus


class ProjectMemberInfo(BaseModel):
    agent_id: str
    name: str
    role: ProjectMemberRole


class ProjectSummary(BaseModel):
    project_id: str
    name: str
    description_md: str | None
    status: ProjectStatus
    proposal_id: str | None
    treasury_wallet_address: str | None
    revenue_wallet_address: str | None
    monthly_budget_micro_usdc: int | None
    created_at: datetime
    updated_at: datetime
    approved_at: datetime | None


class ProjectDetail(ProjectSummary):
    members: list[ProjectMemberInfo]


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
