from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class PayoutSyncRequest(BaseModel):
    tx_hash: str | None = None


class PayoutSyncData(BaseModel):
    profit_month_id: str
    status: str
    tx_hash: str | None
    blocked_reason: str | None
    idempotency_key: str
    executed_at: datetime | None


class PayoutSyncResponse(BaseModel):
    success: bool
    data: PayoutSyncData
