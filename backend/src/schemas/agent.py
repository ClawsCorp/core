from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class AgentRegisterRequest(BaseModel):
    name: str = Field(..., min_length=1)
    capabilities: list[str] = Field(default_factory=list)
    wallet_address: str | None = None


class AgentRegisterResponse(BaseModel):
    agent_id: str
    api_key: str
    created_at: datetime
