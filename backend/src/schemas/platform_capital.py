from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class PlatformCapitalEventCreateRequest(BaseModel):
    idempotency_key: str = Field(..., min_length=1, max_length=255)
    profit_month_id: str | None = Field(default=None, min_length=6, max_length=6)
    delta_micro_usdc: int
    source: str = Field(..., min_length=1, max_length=64)
    evidence_tx_hash: str | None = Field(default=None, min_length=1, max_length=255)
    evidence_url: str | None = Field(default=None, min_length=1, max_length=1024)


class PlatformCapitalEventPublic(BaseModel):
    event_id: str
    idempotency_key: str
    profit_month_id: str | None
    delta_micro_usdc: int
    source: str
    evidence_tx_hash: str | None
    evidence_url: str | None
    created_at: datetime


class PlatformCapitalEventDetailResponse(BaseModel):
    success: bool
    data: PlatformCapitalEventPublic | None
    blocked_reason: str | None = None


class PlatformCapitalSyncData(BaseModel):
    transfers_seen: int
    capital_events_inserted: int
    marketing_fee_events_inserted: int
    marketing_fee_total_micro_usdc: int


class PlatformCapitalSyncResponse(BaseModel):
    success: bool
    data: PlatformCapitalSyncData


class PlatformCapitalReconciliationReportPublic(BaseModel):
    funding_pool_address: str
    ledger_balance_micro_usdc: int | None
    onchain_balance_micro_usdc: int | None
    delta_micro_usdc: int | None
    ready: bool
    blocked_reason: str | None
    computed_at: datetime


class PlatformCapitalReconciliationRunResponse(BaseModel):
    success: bool
    data: PlatformCapitalReconciliationReportPublic


class PlatformCapitalSummaryData(BaseModel):
    funding_pool_address: str | None
    ledger_balance_micro_usdc: int
    spendable_balance_micro_usdc: int
    latest_reconciliation: PlatformCapitalReconciliationReportPublic | None
    blocked_reason: str | None = None


class PlatformCapitalSummaryResponse(BaseModel):
    success: bool
    data: PlatformCapitalSummaryData
