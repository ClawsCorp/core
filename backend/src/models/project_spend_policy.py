from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from src.core.database import Base


class ProjectSpendPolicy(Base):
    __tablename__ = "project_spend_policies"
    __table_args__ = (
        UniqueConstraint("project_id", name="uq_project_spend_policies_project_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(Integer, ForeignKey("projects.id"), nullable=False, index=True)

    # Optional caps. If a cap is NULL, it is not enforced.
    per_bounty_cap_micro_usdc: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    per_day_cap_micro_usdc: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    per_month_cap_micro_usdc: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

