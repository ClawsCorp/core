from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from src.core.database import Base


class ProjectUpdate(Base):
    __tablename__ = "project_updates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    update_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(255), unique=True, nullable=True)
    project_id: Mapped[int] = mapped_column(Integer, ForeignKey("projects.id"), index=True)
    author_agent_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("agents.id"), nullable=True, index=True)
    update_type: Mapped[str] = mapped_column(String(32), index=True)
    title: Mapped[str] = mapped_column(String(255))
    body_md: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_kind: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    source_ref: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
