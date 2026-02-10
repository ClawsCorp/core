from __future__ import annotations

from datetime import datetime
from enum import Enum

from sqlalchemy import (
    DateTime,
    Enum as SqlEnum,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from src.core.database import Base


class VoteChoice(str, Enum):
    approve = "approve"
    reject = "reject"


class Vote(Base):
    __tablename__ = "votes"
    __table_args__ = (
        UniqueConstraint("proposal_id", "voter_agent_id", name="uq_votes_unique"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    proposal_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("proposals.id"), index=True
    )
    voter_agent_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("agents.id"), index=True
    )
    vote: Mapped[VoteChoice] = mapped_column(SqlEnum(VoteChoice, name="vote_choice"))
    reputation_stake: Mapped[int] = mapped_column(Integer)
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
