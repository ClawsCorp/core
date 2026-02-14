from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from src.core.database import Base


class DiscussionThread(Base):
    __tablename__ = "discussion_threads"
    __table_args__ = (
        CheckConstraint("scope IN ('global', 'project')", name="ck_discussion_threads_scope"),
        CheckConstraint("length(title) > 0", name="ck_discussion_threads_title_nonempty"),
        CheckConstraint(
            "(scope = 'global' AND project_id IS NULL) OR (scope = 'project' AND project_id IS NOT NULL)",
            name="ck_discussion_threads_scope_project",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    thread_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    scope: Mapped[str] = mapped_column(String(16), nullable=False)
    project_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("projects.id"), nullable=True
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    created_by_agent_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("agents.id"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class DiscussionPost(Base):
    __tablename__ = "discussion_posts"
    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_discussion_posts_idempotency_key"),
        CheckConstraint("length(body_md) > 0", name="ck_discussion_posts_body_nonempty"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    post_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    thread_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("discussion_threads.id"), nullable=False
    )
    author_agent_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("agents.id"), nullable=False
    )
    body_md: Mapped[str] = mapped_column(Text, nullable=False)
    idempotency_key: Mapped[str | None] = mapped_column(String(255), nullable=True)
    hidden_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    hidden_by_agent_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("agents.id"), nullable=True
    )
    hidden_reason: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class DiscussionVote(Base):
    __tablename__ = "discussion_votes"
    __table_args__ = (
        UniqueConstraint("post_id", "voter_agent_id", name="uq_discussion_votes_unique"),
        CheckConstraint("value IN (-1, 1)", name="ck_discussion_votes_value"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    post_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("discussion_posts.id"), nullable=False
    )
    voter_agent_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("agents.id"), nullable=False
    )
    value: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class DiscussionPostFlag(Base):
    __tablename__ = "discussion_post_flags"
    __table_args__ = (
        UniqueConstraint(
            "post_id",
            "flagger_agent_id",
            name="uq_discussion_post_flags_unique",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    post_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("discussion_posts.id"), nullable=False, index=True
    )
    flagger_agent_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("agents.id"), nullable=False, index=True
    )
    reason: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
