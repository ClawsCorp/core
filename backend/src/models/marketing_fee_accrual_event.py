from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, CheckConstraint, DateTime, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from src.core.database import Base


class MarketingFeeAccrualEvent(Base):
    __tablename__ = "marketing_fee_accrual_events"
    __table_args__ = (
        CheckConstraint("gross_amount_micro_usdc > 0", name="ck_marketing_fee_accrual_gross_positive"),
        CheckConstraint("fee_amount_micro_usdc > 0", name="ck_marketing_fee_accrual_fee_positive"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    event_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    idempotency_key: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    project_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("projects.id"), nullable=True, index=True)
    profit_month_id: Mapped[str | None] = mapped_column(String(6), nullable=True, index=True)
    bucket: Mapped[str] = mapped_column(String(32), index=True)
    source: Mapped[str] = mapped_column(String(64), index=True)
    gross_amount_micro_usdc: Mapped[int] = mapped_column(BigInteger)
    fee_amount_micro_usdc: Mapped[int] = mapped_column(BigInteger)
    chain_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    tx_hash: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    log_index: Mapped[int | None] = mapped_column(Integer, nullable=True)
    evidence_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
