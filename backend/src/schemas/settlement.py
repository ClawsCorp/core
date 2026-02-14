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


class SettlementPayoutPublic(BaseModel):
    tx_hash: str | None
    executed_at: datetime | None
    idempotency_key: str | None
    status: str | None
    confirmed_at: datetime | None
    failed_at: datetime | None
    block_number: int | None


class SettlementDetailData(BaseModel):
    settlement: SettlementPublic | None
    reconciliation: ReconciliationReportPublic | None
    payout: SettlementPayoutPublic | None
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
    payout_tx_hash: str | None
    payout_executed_at: datetime | None
    payout_status: str | None


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
    task_id: str | None = None


class DistributionCreateResponse(BaseModel):
    success: bool
    data: DistributionCreateData


class DistributionExecuteRequest(BaseModel):
    stakers: list[str]
    staker_shares: list[int]
    authors: list[str]
    author_shares: list[int]
    idempotency_key: str | None = None


class DistributionExecuteData(BaseModel):
    profit_month_id: str
    status: str
    tx_hash: str | None
    blocked_reason: str | None
    idempotency_key: str
    task_id: str | None = None


class DistributionExecuteResponse(BaseModel):
    success: bool
    data: DistributionExecuteData


class DistributionCreateRecordRequest(BaseModel):
    idempotency_key: str = Field(..., min_length=1, max_length=255)
    profit_sum_micro_usdc: int = Field(..., ge=0)
    tx_hash: str = Field(..., min_length=1, max_length=80)


class DistributionExecuteRecordRequest(BaseModel):
    idempotency_key: str = Field(..., min_length=1, max_length=255)
    tx_hash: str = Field(..., min_length=1, max_length=80)
    total_profit_micro_usdc: int = Field(..., ge=0)
    stakers_count: int = Field(..., ge=0)
    authors_count: int = Field(..., ge=0)
