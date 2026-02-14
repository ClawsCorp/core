from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Index, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from src.core.database import Base


class ObservedUsdcTransfer(Base):
    __tablename__ = "observed_usdc_transfers"
    __table_args__ = (
        UniqueConstraint("chain_id", "tx_hash", "log_index", name="uq_observed_usdc_transfer"),
        Index("ix_observed_usdc_transfers_block", "chain_id", "block_number"),
        Index("ix_observed_usdc_transfers_to", "chain_id", "to_address", "block_number"),
        Index("ix_observed_usdc_transfers_from", "chain_id", "from_address", "block_number"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    chain_id: Mapped[int] = mapped_column(Integer, nullable=False)
    token_address: Mapped[str] = mapped_column(String(42), nullable=False)
    from_address: Mapped[str] = mapped_column(String(42), nullable=False)
    to_address: Mapped[str] = mapped_column(String(42), nullable=False)
    amount_micro_usdc: Mapped[int] = mapped_column(BigInteger, nullable=False)
    block_number: Mapped[int] = mapped_column(BigInteger, nullable=False)
    tx_hash: Mapped[str] = mapped_column(String(66), nullable=False)
    log_index: Mapped[int] = mapped_column(Integer, nullable=False)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

