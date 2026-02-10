from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from src.core.database import Base


class Settlement(Base):
    __tablename__ = "settlements"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    profit_month_id: Mapped[str] = mapped_column(String(6), index=True)
    revenue_sum_micro_usdc: Mapped[int] = mapped_column(Integer)
    expense_sum_micro_usdc: Mapped[int] = mapped_column(Integer)
    profit_sum_micro_usdc: Mapped[int] = mapped_column(Integer)
    profit_nonnegative: Mapped[bool] = mapped_column(Boolean, nullable=False)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    computed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )
