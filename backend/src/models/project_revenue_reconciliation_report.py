from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Index, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from src.core.database import Base


class ProjectRevenueReconciliationReport(Base):
    __tablename__ = "project_revenue_reconciliation_reports"
    __table_args__ = (
        Index("ix_project_revenue_recon_project_computed", "project_id", "computed_at"),
        Index("ix_project_revenue_recon_ready_computed", "ready", "computed_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(Integer, ForeignKey("projects.id"), index=True)
    revenue_address: Mapped[str] = mapped_column(String(42))
    ledger_balance_micro_usdc: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    onchain_balance_micro_usdc: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    delta_micro_usdc: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    ready: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    blocked_reason: Mapped[str | None] = mapped_column(String(64), nullable=True)
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)

