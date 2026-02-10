from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class RevenueEventCreateRequest(BaseModel):
    profit_month_id: str = Field(..., min_length=6, max_length=6)
    project_id: str | None = None
    amount_micro_usdc: int = Field(..., gt=0)
    tx_hash: str | None = None
    source: str = Field(..., min_length=1)
    idempotency_key: str = Field(..., min_length=1)
    evidence_url: str | None = None


class ExpenseEventCreateRequest(BaseModel):
    profit_month_id: str = Field(..., min_length=6, max_length=6)
    project_id: str | None = None
    amount_micro_usdc: int = Field(..., gt=0)
    tx_hash: str | None = None
    category: str = Field(..., min_length=1)
    idempotency_key: str = Field(..., min_length=1)
    evidence_url: str | None = None


class RevenueEventPublic(BaseModel):
    event_id: str
    profit_month_id: str
    project_id: str | None
    amount_micro_usdc: int
    tx_hash: str | None
    source: str
    idempotency_key: str
    evidence_url: str | None
    created_at: datetime


class ExpenseEventPublic(BaseModel):
    event_id: str
    profit_month_id: str
    project_id: str | None
    amount_micro_usdc: int
    tx_hash: str | None
    category: str
    idempotency_key: str
    evidence_url: str | None
    created_at: datetime


class RevenueEventDetailResponse(BaseModel):
    success: bool
    data: RevenueEventPublic


class ExpenseEventDetailResponse(BaseModel):
    success: bool
    data: ExpenseEventPublic


class AccountingMonthSummary(BaseModel):
    profit_month_id: str
    revenue_sum_micro_usdc: int
    expense_sum_micro_usdc: int
    profit_sum_micro_usdc: int


class AccountingMonthsData(BaseModel):
    items: list[AccountingMonthSummary]
    limit: int
    offset: int
    total: int


class AccountingMonthsResponse(BaseModel):
    success: bool
    data: AccountingMonthsData

