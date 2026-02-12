from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from src.core.database import Base


class DistributionCreation(Base):
    __tablename__ = "distribution_creations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    profit_month_id: Mapped[str] = mapped_column(String(6), index=True)
    profit_sum_micro_usdc: Mapped[int] = mapped_column(BigInteger, nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    tx_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
