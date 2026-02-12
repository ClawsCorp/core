from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from src.core.database import Base


class DistributionExecution(Base):
    __tablename__ = "distribution_executions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    profit_month_id: Mapped[str] = mapped_column(String(6), index=True)
    idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    tx_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    blocked_reason: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
