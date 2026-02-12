"""add distribution executions table

Revision ID: 0011_distribution_executions
Revises: 0010_audit_log_error_hint
Create Date: 2026-02-12 00:00:00.000000

"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "0011_distribution_executions"
down_revision = "0010_audit_log_error_hint"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "distribution_executions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("profit_month_id", sa.String(length=6), nullable=False),
        sa.Column("idempotency_key", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("tx_hash", sa.String(length=255), nullable=True),
        sa.Column("blocked_reason", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("idempotency_key"),
    )
    op.create_index(
        "ix_distribution_executions_profit_month_id",
        "distribution_executions",
        ["profit_month_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_distribution_executions_profit_month_id", table_name="distribution_executions")
    op.drop_table("distribution_executions")
