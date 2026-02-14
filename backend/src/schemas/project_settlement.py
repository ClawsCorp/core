from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class ProjectSettlementPublic(BaseModel):
    project_id: str
    profit_month_id: str
    revenue_sum_micro_usdc: int
    expense_sum_micro_usdc: int
    profit_sum_micro_usdc: int
    profit_nonnegative: bool
    note: str | None
    computed_at: datetime


class ProjectSettlementDetailData(BaseModel):
    settlement: ProjectSettlementPublic | None


class ProjectSettlementDetailResponse(BaseModel):
    success: bool
    data: ProjectSettlementDetailData

