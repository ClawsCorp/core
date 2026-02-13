"""payout confirmation status fields

Revision ID: 0020_payout_confirm_status
Revises: 0019_bigint_money_oracle_nonce
Create Date: 2026-02-13 00:00:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0020_payout_confirm_status"
down_revision = "0019_bigint_money_oracle_nonce"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("dividend_payouts", sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("dividend_payouts", sa.Column("failed_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("dividend_payouts", sa.Column("block_number", sa.BigInteger(), nullable=True))

    op.execute(
        """
        UPDATE dividend_payouts
        SET status = CASE
            WHEN status = 'submitted' THEN 'pending'
            ELSE status
        END
        """
    )


def downgrade() -> None:
    op.execute(
        """
        UPDATE dividend_payouts
        SET status = CASE
            WHEN status = 'pending' THEN 'submitted'
            ELSE status
        END
        """
    )
    op.drop_column("dividend_payouts", "block_number")
    op.drop_column("dividend_payouts", "failed_at")
    op.drop_column("dividend_payouts", "confirmed_at")
