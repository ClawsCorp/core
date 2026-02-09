from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


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
