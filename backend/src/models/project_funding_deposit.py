from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from src.core.database import Base


class ProjectFundingDeposit(Base):
    __tablename__ = "project_funding_deposits"
    __table_args__ = (
        UniqueConstraint("observed_transfer_id", name="uq_project_funding_deposits_observed_transfer_id"),
        Index("ix_project_funding_deposits_project_round", "project_id", "funding_round_id", "block_number"),
        Index("ix_project_funding_deposits_project_from", "project_id", "from_address", "block_number"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    deposit_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    project_id: Mapped[int] = mapped_column(Integer, ForeignKey("projects.id"), nullable=False, index=True)
    funding_round_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("project_funding_rounds.id"), nullable=True, index=True
    )
    observed_transfer_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("observed_usdc_transfers.id"), nullable=False
    )
    chain_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    from_address: Mapped[str] = mapped_column(String(42), nullable=False, index=True)
    to_address: Mapped[str] = mapped_column(String(42), nullable=False, index=True)
    amount_micro_usdc: Mapped[int] = mapped_column(BigInteger, nullable=False)
    block_number: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    tx_hash: Mapped[str] = mapped_column(String(66), nullable=False, index=True)
    log_index: Mapped[int] = mapped_column(Integer, nullable=False)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

