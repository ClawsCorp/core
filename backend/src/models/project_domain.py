from __future__ import annotations

import secrets
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from src.core.database import Base


def _new_dns_token() -> str:
    # Short, URL-safe token for DNS TXT verification.
    return secrets.token_urlsafe(24)

def _new_domain_id() -> str:
    for _ in range(5):
        return f"pdom_{secrets.token_hex(8)}"
    raise RuntimeError("Failed to generate domain id")

class ProjectDomainStatus(str):
    pending = "pending"
    verified = "verified"
    failed = "failed"


class ProjectDomain(Base):
    __tablename__ = "project_domains"
    __table_args__ = (
        UniqueConstraint("domain", name="uq_project_domains_domain"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    domain_id: Mapped[str] = mapped_column(String(64), unique=True, index=True, default=_new_domain_id)
    project_id: Mapped[int] = mapped_column(Integer, ForeignKey("projects.id"), nullable=False, index=True)
    domain: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default=ProjectDomainStatus.pending, server_default=ProjectDomainStatus.pending)
    dns_txt_token: Mapped[str] = mapped_column(String(128), nullable=False, default=_new_dns_token)

    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_check_error: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
