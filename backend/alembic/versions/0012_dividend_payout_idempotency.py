"""add dividend payout idempotency and totals columns

Revision ID: 0012_dividend_payout_idempotency
Revises: 0011_distribution_executions
Create Date: 2026-02-12 00:00:00.000000

"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0012_dividend_payout_idempotency"
down_revision = "0011_distribution_executions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("dividend_payouts", sa.Column("idempotency_key", sa.String(length=255), nullable=True))
    op.add_column(
        "dividend_payouts",
        sa.Column("total_treasury_micro_usdc", sa.BigInteger(), nullable=False, server_default="0"),
    )
    op.add_column(
        "dividend_payouts",
        sa.Column("total_founder_micro_usdc", sa.BigInteger(), nullable=False, server_default="0"),
    )
    op.create_unique_constraint(
        "uq_dividend_payouts_idempotency_key",
        "dividend_payouts",
        ["idempotency_key"],
    )
    op.create_unique_constraint(
        "uq_dividend_payouts_profit_month_id_tx_hash",
        "dividend_payouts",
        ["profit_month_id", "tx_hash"],
    )


def downgrade() -> None:
    op.drop_constraint("uq_dividend_payouts_profit_month_id_tx_hash", "dividend_payouts", type_="unique")
    op.drop_constraint("uq_dividend_payouts_idempotency_key", "dividend_payouts", type_="unique")
    op.drop_column("dividend_payouts", "total_founder_micro_usdc")
    op.drop_column("dividend_payouts", "total_treasury_micro_usdc")
    op.drop_column("dividend_payouts", "idempotency_key")
