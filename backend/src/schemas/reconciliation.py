from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class ReconciliationReportPublic(BaseModel):
    profit_month_id: str
    revenue_sum_micro_usdc: int
    expense_sum_micro_usdc: int
    profit_sum_micro_usdc: int
    distributor_balance_micro_usdc: int
    delta_micro_usdc: int
    ready: bool
    blocked_reason: str
    rpc_chain_id: int | None
    rpc_url_name: str | None
    computed_at: datetime
