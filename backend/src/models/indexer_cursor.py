from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Index, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from src.core.database import Base


class IndexerCursor(Base):
    __tablename__ = "indexer_cursors"
    __table_args__ = (
        UniqueConstraint("cursor_key", "chain_id", name="uq_indexer_cursor_key_chain"),
        Index("ix_indexer_cursors_key_chain", "cursor_key", "chain_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    cursor_key: Mapped[str] = mapped_column(String(64), nullable=False)
    chain_id: Mapped[int] = mapped_column(Integer, nullable=False)
    last_block_number: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

