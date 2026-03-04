"""platform capital ledger

Revision ID: 0046
Revises: 0045
Create Date: 2026-03-04 00:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0046"
down_revision = "0045"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "platform_capital_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("event_id", sa.String(length=64), nullable=False),
        sa.Column("idempotency_key", sa.String(length=255), nullable=False),
        sa.Column("profit_month_id", sa.String(length=6), nullable=True),
        sa.Column("delta_micro_usdc", sa.BigInteger(), nullable=False),
        sa.Column("source", sa.String(length=64), nullable=False),
        sa.Column("evidence_tx_hash", sa.String(length=255), nullable=True),
        sa.Column("evidence_url", sa.String(length=1024), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("delta_micro_usdc != 0", name="ck_platform_capital_events_delta_nonzero"),
        sa.UniqueConstraint("event_id"),
        sa.UniqueConstraint("idempotency_key"),
    )
    op.create_index("ix_platform_capital_events_event_id", "platform_capital_events", ["event_id"])
    op.create_index(
        "ix_platform_capital_events_idempotency_key", "platform_capital_events", ["idempotency_key"]
    )
    op.create_index("ix_platform_capital_events_profit_month_id", "platform_capital_events", ["profit_month_id"])
    op.create_index("ix_platform_capital_events_source", "platform_capital_events", ["source"])
    op.create_index(
        "ix_platform_capital_events_evidence_tx_hash", "platform_capital_events", ["evidence_tx_hash"]
    )

    op.create_table(
        "platform_capital_reconciliation_reports",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("funding_pool_address", sa.String(length=42), nullable=False),
        sa.Column("ledger_balance_micro_usdc", sa.BigInteger(), nullable=True),
        sa.Column("onchain_balance_micro_usdc", sa.BigInteger(), nullable=True),
        sa.Column("delta_micro_usdc", sa.BigInteger(), nullable=True),
        sa.Column("ready", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("blocked_reason", sa.String(length=64), nullable=True),
        sa.Column("computed_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index(
        "ix_platform_capital_reconciliation_reports_computed_at",
        "platform_capital_reconciliation_reports",
        ["computed_at"],
    )
    op.create_index(
        "ix_platform_capital_recon_ready_computed",
        "platform_capital_reconciliation_reports",
        ["ready", "computed_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_platform_capital_recon_ready_computed", table_name="platform_capital_reconciliation_reports")
    op.drop_index(
        "ix_platform_capital_reconciliation_reports_computed_at",
        table_name="platform_capital_reconciliation_reports",
    )
    op.drop_table("platform_capital_reconciliation_reports")

    op.drop_index("ix_platform_capital_events_evidence_tx_hash", table_name="platform_capital_events")
    op.drop_index("ix_platform_capital_events_source", table_name="platform_capital_events")
    op.drop_index("ix_platform_capital_events_profit_month_id", table_name="platform_capital_events")
    op.drop_index("ix_platform_capital_events_idempotency_key", table_name="platform_capital_events")
    op.drop_index("ix_platform_capital_events_event_id", table_name="platform_capital_events")
    op.drop_table("platform_capital_events")
