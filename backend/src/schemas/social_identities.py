from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class AgentSocialIdentityCreateRequest(BaseModel):
    platform: str = Field(..., min_length=1, max_length=32)
    handle: str = Field(..., min_length=1, max_length=128)
    idempotency_key: str | None = Field(default=None, min_length=1, max_length=255)


class AgentSocialIdentityPublic(BaseModel):
    identity_id: str
    agent_id: str
    platform: str
    handle: str
    status: str
    created_at: datetime
    updated_at: datetime
    revoked_at: datetime | None


class AgentSocialIdentityListData(BaseModel):
    items: list[AgentSocialIdentityPublic]


class AgentSocialIdentityListResponse(BaseModel):
    success: bool
    data: AgentSocialIdentityListData


class AgentSocialIdentityResponse(BaseModel):
    success: bool
    data: AgentSocialIdentityPublic
