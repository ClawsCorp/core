"""add settlements reconciliation reports and dividend payouts

Revision ID: 0007_settlement_reports_payouts
Revises: 0006_accounting_events
Create Date: 2024-01-07 00:00:00.000000

"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
# IMPORTANT: Alembic's default `alembic_version.version_num` column is VARCHAR(32).
# Keep revision identifiers <= 32 chars to avoid truncation errors on upgrade.
revision = "0007_settlement_reports_payouts"
down_revision = "0006_accounting_events"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "settlements",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("profit_month_id", sa.String(length=6), nullable=False),
        sa.Column("revenue_sum_micro_usdc", sa.Integer(), nullable=False),
        sa.Column("expense_sum_micro_usdc", sa.Integer(), nullable=False),
        sa.Column("profit_sum_micro_usdc", sa.Integer(), nullable=False),
        sa.Column("profit_nonnegative", sa.Boolean(), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column(
            "computed_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_settlements_profit_month_id", "settlements", ["profit_month_id"], unique=False)
    op.create_index("ix_settlements_computed_at", "settlements", ["computed_at"], unique=False)

    op.create_table(
        "reconciliation_reports",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("profit_month_id", sa.String(length=6), nullable=False),
        sa.Column("revenue_sum_micro_usdc", sa.Integer(), nullable=False),
        sa.Column("expense_sum_micro_usdc", sa.Integer(), nullable=False),
        sa.Column("profit_sum_micro_usdc", sa.Integer(), nullable=False),
        sa.Column("distributor_balance_micro_usdc", sa.BigInteger(), nullable=False),
        sa.Column("delta_micro_usdc", sa.BigInteger(), nullable=False),
        sa.Column("ready", sa.Boolean(), nullable=False),
        sa.Column("blocked_reason", sa.String(length=64), nullable=False),
        sa.Column("rpc_chain_id", sa.Integer(), nullable=True),
        sa.Column("rpc_url_name", sa.Text(), nullable=True),
        sa.Column(
            "computed_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_reconciliation_reports_profit_month_id",
        "reconciliation_reports",
        ["profit_month_id"],
        unique=False,
    )
    op.create_index(
        "ix_reconciliation_reports_computed_at",
        "reconciliation_reports",
        ["computed_at"],
        unique=False,
    )

    op.create_table(
        "dividend_payouts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("profit_month_id", sa.String(length=6), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("tx_hash", sa.String(length=255), nullable=True),
        sa.Column("stakers_count", sa.Integer(), nullable=False),
        sa.Column("authors_count", sa.Integer(), nullable=False),
        sa.Column("total_stakers_micro_usdc", sa.BigInteger(), nullable=False),
        sa.Column("total_authors_micro_usdc", sa.BigInteger(), nullable=False),
        sa.Column("total_payout_micro_usdc", sa.BigInteger(), nullable=False),
        sa.Column("payout_executed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_dividend_payouts_profit_month_id",
        "dividend_payouts",
        ["profit_month_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_dividend_payouts_profit_month_id", table_name="dividend_payouts")
    op.drop_table("dividend_payouts")

    op.drop_index(
        "ix_reconciliation_reports_computed_at", table_name="reconciliation_reports"
    )
    op.drop_index(
        "ix_reconciliation_reports_profit_month_id", table_name="reconciliation_reports"
    )
    op.drop_table("reconciliation_reports")

    op.drop_index("ix_settlements_computed_at", table_name="settlements")
    op.drop_index("ix_settlements_profit_month_id", table_name="settlements")
    op.drop_table("settlements")
