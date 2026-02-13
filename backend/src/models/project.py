from __future__ import annotations

from datetime import datetime
from enum import Enum

from sqlalchemy import BigInteger, DateTime, Enum as SqlEnum, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from src.core.database import Base


class ProjectStatus(str, Enum):
    draft = "draft"
    fundraising = "fundraising"
    active = "active"
    paused = "paused"
    archived = "archived"


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(255))
    description_md: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[ProjectStatus] = mapped_column(
        SqlEnum(ProjectStatus, name="project_status")
    )
    proposal_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    origin_proposal_id: Mapped[str | None] = mapped_column(String(64), nullable=True, unique=True, index=True)
    originator_agent_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("agents.id"), nullable=True, index=True)
    treasury_wallet_address: Mapped[str | None] = mapped_column(
        String(255), nullable=True
    )
    revenue_wallet_address: Mapped[str | None] = mapped_column(String(255), nullable=True)
    monthly_budget_micro_usdc: Mapped[int | None] = mapped_column(
        BigInteger, nullable=True
    )
    created_by_agent_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("agents.id"), nullable=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    approved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
