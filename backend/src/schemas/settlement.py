from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from src.schemas.reconciliation import ReconciliationReportPublic


class SettlementPublic(BaseModel):
    profit_month_id: str
    revenue_sum_micro_usdc: int
    expense_sum_micro_usdc: int
    profit_sum_micro_usdc: int
    profit_nonnegative: bool
    note: str | None
    computed_at: datetime


class SettlementDetailData(BaseModel):
    settlement: SettlementPublic | None
    reconciliation: ReconciliationReportPublic | None
    ready: bool


class SettlementDetailResponse(BaseModel):
    success: bool
    data: SettlementDetailData


class SettlementMonthSummary(BaseModel):
    profit_month_id: str
    revenue_sum_micro_usdc: int
    expense_sum_micro_usdc: int
    profit_sum_micro_usdc: int
    distributor_balance_micro_usdc: int | None
    delta_micro_usdc: int | None
    ready: bool
    blocked_reason: str | None
    settlement_computed_at: datetime | None
    reconciliation_computed_at: datetime | None


class SettlementMonthsData(BaseModel):
    items: list[SettlementMonthSummary]
    limit: int
    offset: int
    total: int


class SettlementMonthsResponse(BaseModel):
    success: bool
    data: SettlementMonthsData


class PayoutTriggerRequest(BaseModel):
    stakers_count: int = Field(..., ge=0)
    authors_count: int = Field(..., ge=0)
    total_stakers_micro_usdc: int = Field(..., ge=0)
    total_authors_micro_usdc: int = Field(..., ge=0)


class PayoutTriggerData(BaseModel):
    profit_month_id: str
    status: str
    tx_hash: str | None
    blocked_reason: str | None


class PayoutTriggerResponse(BaseModel):
    success: bool
    data: PayoutTriggerData


class DistributionCreateData(BaseModel):
    profit_month_id: str
    status: str
    tx_hash: str | None
    blocked_reason: str | None
    idempotency_key: str


class DistributionCreateResponse(BaseModel):
    success: bool
    data: DistributionCreateData
