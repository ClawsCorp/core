from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from src.core.database import Base


class ObservedSocialSignalDecision(Base):
    __tablename__ = "observed_social_signal_decisions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    decision_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    decision_key: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    observed_social_signal_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("observed_social_signals.id"),
        nullable=False,
        index=True,
    )
    decision_status: Mapped[str] = mapped_column(String(24), nullable=False, index=True)
    reason_code: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    identity_key: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    reputation_event_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("reputation_events.id"),
        nullable=True,
        index=True,
    )
    note: Mapped[str | None] = mapped_column(String(255), nullable=True)
    decided_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
