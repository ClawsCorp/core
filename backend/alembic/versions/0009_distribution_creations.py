"""add distribution creation tracking and audit tx hash

Revision ID: 0009_distribution_creations
Revises: 0008_recon_nullable_fields
Create Date: 2024-01-09 00:00:00.000000

"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "0009_distribution_creations"
down_revision = "0008_recon_nullable_fields"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("audit_logs", sa.Column("tx_hash", sa.String(length=255), nullable=True))

    op.create_table(
        "distribution_creations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("profit_month_id", sa.String(length=6), nullable=False),
        sa.Column("profit_sum_micro_usdc", sa.BigInteger(), nullable=False),
        sa.Column("idempotency_key", sa.String(length=255), nullable=False),
        sa.Column("tx_hash", sa.String(length=255), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint("idempotency_key", name="uq_distribution_creations_idempotency_key"),
    )
    op.create_index(
        "ix_distribution_creations_profit_month_id",
        "distribution_creations",
        ["profit_month_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_distribution_creations_profit_month_id", table_name="distribution_creations")
    op.drop_table("distribution_creations")
    op.drop_column("audit_logs", "tx_hash")
