"""allow null reconciliation rpc failure fields

Revision ID: 0008_recon_nullable_fields
Revises: 0007_settlement_reports_payouts
Create Date: 2026-02-11 00:00:00.000000

"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "0008_recon_nullable_fields"
down_revision = "0007_settlement_reports_payouts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "reconciliation_reports",
        "distributor_balance_micro_usdc",
        existing_type=sa.BigInteger(),
        nullable=True,
    )
    op.alter_column(
        "reconciliation_reports",
        "delta_micro_usdc",
        existing_type=sa.BigInteger(),
        nullable=True,
    )
    op.alter_column(
        "reconciliation_reports",
        "blocked_reason",
        existing_type=sa.String(length=64),
        nullable=True,
    )


def downgrade() -> None:
    op.alter_column(
        "reconciliation_reports",
        "blocked_reason",
        existing_type=sa.String(length=64),
        nullable=False,
    )
    op.alter_column(
        "reconciliation_reports",
        "delta_micro_usdc",
        existing_type=sa.BigInteger(),
        nullable=False,
    )
    op.alter_column(
        "reconciliation_reports",
        "distributor_balance_micro_usdc",
        existing_type=sa.BigInteger(),
        nullable=False,
    )
