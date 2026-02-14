from __future__ import annotations

from datetime import datetime
from enum import Enum

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    Enum as SqlEnum,
    ForeignKey,
    Index,
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


class BountyFundingSource(str, Enum):
    project_capital = "project_capital"
    project_revenue = "project_revenue"
    platform_treasury = "platform_treasury"


def _default_bounty_funding_source(context) -> BountyFundingSource:
    project_id = context.get_current_parameters().get("project_id")
    if project_id is None:
        return BountyFundingSource.platform_treasury
    return BountyFundingSource.project_capital


class Bounty(Base):
    __tablename__ = "bounties"
    __table_args__ = (
        CheckConstraint("amount_micro_usdc >= 0", name="ck_bounties_amount_nonneg"),
        Index("ix_bounties_origin_proposal_id", "origin_proposal_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    bounty_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(255), nullable=True, unique=True, index=True)
    project_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("projects.id"), nullable=True, index=True
    )
    # Public proposal_id (string), used to link marketplace bounties to governance proposals.
    origin_proposal_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    funding_source: Mapped[BountyFundingSource] = mapped_column(
        SqlEnum(BountyFundingSource, name="bounty_funding_source"),
        nullable=False,
        default=_default_bounty_funding_source,
    )
    title: Mapped[str] = mapped_column(String(255))
    description_md: Mapped[str | None] = mapped_column(Text, nullable=True)
    amount_micro_usdc: Mapped[int] = mapped_column(BigInteger)
    priority: Mapped[str | None] = mapped_column(String(16), nullable=True)
    deadline_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
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
