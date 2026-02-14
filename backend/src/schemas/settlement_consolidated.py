from __future__ import annotations

from pydantic import BaseModel

from src.schemas.project_settlement import ProjectSettlementPublic
from src.schemas.settlement import SettlementDetailData


class ConsolidatedSettlementProjectsSums(BaseModel):
    projects_revenue_sum_micro_usdc: int
    projects_expense_sum_micro_usdc: int
    projects_profit_sum_micro_usdc: int
    projects_with_settlement_count: int


class ConsolidatedSettlementData(BaseModel):
    profit_month_id: str
    platform: SettlementDetailData
    projects: list[ProjectSettlementPublic]
    sums: ConsolidatedSettlementProjectsSums


class ConsolidatedSettlementResponse(BaseModel):
    success: bool
    data: ConsolidatedSettlementData

