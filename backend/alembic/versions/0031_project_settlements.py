"""project settlements (per project profit months)

Revision ID: 0031_project_settlements
Revises: 0030_tx_outbox_crash_safe
Create Date: 2026-02-14 00:00:00.000000

"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0031_project_settlements"
down_revision = "0030_tx_outbox_crash_safe"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "project_settlements",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("projects.id"), nullable=False, index=True),
        sa.Column("profit_month_id", sa.String(length=6), nullable=False, index=True),
        sa.Column("revenue_sum_micro_usdc", sa.BigInteger(), nullable=False),
        sa.Column("expense_sum_micro_usdc", sa.BigInteger(), nullable=False),
        sa.Column("profit_sum_micro_usdc", sa.BigInteger(), nullable=False),
        sa.Column("profit_nonnegative", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("computed_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Index("ix_project_settlements_project_month", "project_id", "profit_month_id", "computed_at"),
    )


def downgrade() -> None:
    op.drop_table("project_settlements")

