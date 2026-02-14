from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Integer, String, Text, func, Index
from sqlalchemy.orm import Mapped, mapped_column

from src.core.database import Base


class ProjectSettlement(Base):
    __tablename__ = "project_settlements"
    __table_args__ = (
        Index("ix_project_settlements_project_month", "project_id", "profit_month_id", "computed_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(Integer, ForeignKey("projects.id"), index=True)
    profit_month_id: Mapped[str] = mapped_column(String(6), index=True)

    revenue_sum_micro_usdc: Mapped[int] = mapped_column(BigInteger)
    expense_sum_micro_usdc: Mapped[int] = mapped_column(BigInteger)
    profit_sum_micro_usdc: Mapped[int] = mapped_column(BigInteger)
    profit_nonnegative: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

