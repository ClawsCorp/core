# SPDX-License-Identifier: BSL-1.1

from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from src.core.database import Base


class ProjectCryptoInvoice(Base):
    __tablename__ = "project_crypto_invoices"
    __table_args__ = (
        UniqueConstraint("invoice_id", name="uq_project_crypto_invoices_invoice_id"),
        UniqueConstraint("idempotency_key", name="uq_project_crypto_invoices_idempotency_key"),
        UniqueConstraint("observed_transfer_id", name="uq_project_crypto_invoices_observed_transfer_id"),
        Index("ix_project_crypto_invoices_project_status", "project_id", "status", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    invoice_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(255), nullable=True)

    project_id: Mapped[int] = mapped_column(Integer, ForeignKey("projects.id"), nullable=False, index=True)
    creator_agent_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("agents.id"), nullable=True, index=True)

    chain_id: Mapped[int] = mapped_column(Integer, nullable=False)
    token_address: Mapped[str | None] = mapped_column(String(42), nullable=True)
    payment_address: Mapped[str] = mapped_column(String(42), nullable=False)
    payer_address: Mapped[str | None] = mapped_column(String(42), nullable=True)
    amount_micro_usdc: Mapped[int] = mapped_column(BigInteger, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    status: Mapped[str] = mapped_column(String(16), nullable=False, index=True)  # pending|paid|cancelled|expired

    observed_transfer_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("observed_usdc_transfers.id"),
        nullable=True,
        index=True,
    )
    paid_tx_hash: Mapped[str | None] = mapped_column(String(66), nullable=True)
    paid_log_index: Mapped[int | None] = mapped_column(Integer, nullable=True)
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
