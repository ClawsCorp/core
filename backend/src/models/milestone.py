# SPDX-License-Identifier: BSL-1.1

from __future__ import annotations

from datetime import datetime
from enum import Enum

from sqlalchemy import DateTime, Enum as SqlEnum, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from src.core.database import Base


class MilestoneStatus(str, Enum):
    planned = "planned"
    in_progress = "in_progress"
    done = "done"


class Milestone(Base):
    __tablename__ = "milestones"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    milestone_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(255), nullable=True, unique=True, index=True)

    proposal_id: Mapped[int] = mapped_column(Integer, ForeignKey("proposals.id"), index=True)

    title: Mapped[str] = mapped_column(String(255))
    description_md: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[MilestoneStatus] = mapped_column(SqlEnum(MilestoneStatus, name="milestone_status"))

    priority: Mapped[str | None] = mapped_column(String(16), nullable=True)
    deadline_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
