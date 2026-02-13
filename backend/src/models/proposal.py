from __future__ import annotations

from datetime import datetime
from enum import Enum

from sqlalchemy import DateTime, Enum as SqlEnum, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from src.core.database import Base


class ProposalStatus(str, Enum):
    draft = "draft"
    discussion = "discussion"
    voting = "voting"
    approved = "approved"
    rejected = "rejected"


class Proposal(Base):
    __tablename__ = "proposals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    proposal_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    title: Mapped[str] = mapped_column(String(255))
    description_md: Mapped[str] = mapped_column(Text)
    status: Mapped[ProposalStatus] = mapped_column(
        SqlEnum(ProposalStatus, name="proposal_status")
    )
    author_agent_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("agents.id"), index=True
    )
    discussion_ends_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    voting_starts_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    voting_ends_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    finalized_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    finalized_outcome: Mapped[str | None] = mapped_column(String(16), nullable=True)
    yes_votes_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    no_votes_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
