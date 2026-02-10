from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from core.database import Base


class ReconciliationReport(Base):
    __tablename__ = "reconciliation_reports"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    profit_month_id: Mapped[str] = mapped_column(String(6), index=True)
    revenue_sum_micro_usdc: Mapped[int] = mapped_column(Integer)
    expense_sum_micro_usdc: Mapped[int] = mapped_column(Integer)
    profit_sum_micro_usdc: Mapped[int] = mapped_column(Integer)
    distributor_balance_micro_usdc: Mapped[int] = mapped_column(BigInteger)
    delta_micro_usdc: Mapped[int] = mapped_column(BigInteger)
    ready: Mapped[bool] = mapped_column(Boolean, nullable=False)
    blocked_reason: Mapped[str] = mapped_column(String(64), nullable=False)
    rpc_chain_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    rpc_url_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    computed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )
