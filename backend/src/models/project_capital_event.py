from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, CheckConstraint, DateTime, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from src.core.database import Base


class ProjectCapitalEvent(Base):
    __tablename__ = "project_capital_events"
    __table_args__ = (
        CheckConstraint("delta_micro_usdc != 0", name="ck_project_capital_events_delta_nonzero"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    event_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    idempotency_key: Mapped[str] = mapped_column(String(255), unique=True)
    profit_month_id: Mapped[str | None] = mapped_column(String(6), nullable=True, index=True)
    project_id: Mapped[int] = mapped_column(Integer, ForeignKey("projects.id"), index=True)
    delta_micro_usdc: Mapped[int] = mapped_column(BigInteger)
    source: Mapped[str] = mapped_column(String(64), index=True)
    evidence_tx_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    evidence_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
