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


class PayoutConfirmRequest(BaseModel):
    tx_hash: str | None = None


class PayoutConfirmData(BaseModel):
    profit_month_id: str
    status: str
    tx_hash: str | None
    blocked_reason: str | None
    idempotency_key: str
    confirmed_at: datetime | None
    failed_at: datetime | None
    block_number: int | None


class PayoutConfirmResponse(BaseModel):
    success: bool
    data: PayoutConfirmData
