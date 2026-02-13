from __future__ import annotations

from datetime import datetime
from enum import Enum

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Enum as SqlEnum,
    ForeignKey,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from src.core.database import Base


class BountyStatus(str, Enum):
    open = "open"
    claimed = "claimed"
    submitted = "submitted"
    eligible_for_payout = "eligible_for_payout"
    paid = "paid"


class Bounty(Base):
    __tablename__ = "bounties"
    __table_args__ = (
        CheckConstraint("amount_micro_usdc >= 0", name="ck_bounties_amount_nonneg"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    bounty_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    project_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("projects.id"), nullable=True, index=True
    )
    title: Mapped[str] = mapped_column(String(255))
    description_md: Mapped[str | None] = mapped_column(Text, nullable=True)
    amount_micro_usdc: Mapped[int] = mapped_column(Integer)
    status: Mapped[BountyStatus] = mapped_column(
        SqlEnum(BountyStatus, name="bounty_status")
    )
    claimant_agent_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("agents.id"), nullable=True, index=True
    )
    claimed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    submitted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    pr_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    merge_sha: Mapped[str | None] = mapped_column(String(64), nullable=True)
    paid_tx_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
