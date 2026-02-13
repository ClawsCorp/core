from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from src.core.database import Base


class DividendPayout(Base):
    __tablename__ = "dividend_payouts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    profit_month_id: Mapped[str] = mapped_column(String(6), index=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(255), nullable=True, unique=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="blocked")
    tx_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    stakers_count: Mapped[int] = mapped_column(Integer, nullable=False)
    authors_count: Mapped[int] = mapped_column(Integer, nullable=False)
    total_stakers_micro_usdc: Mapped[int] = mapped_column(BigInteger, nullable=False)
    total_treasury_micro_usdc: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    total_authors_micro_usdc: Mapped[int] = mapped_column(BigInteger, nullable=False)
    total_founder_micro_usdc: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    total_payout_micro_usdc: Mapped[int] = mapped_column(BigInteger, nullable=False)
    payout_executed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    failed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    block_number: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
