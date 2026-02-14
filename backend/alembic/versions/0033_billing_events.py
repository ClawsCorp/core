"""billing events

Revision ID: 0033_billing_events
Revises: 0032_project_spend_policies
Create Date: 2026-02-14
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0033_billing_events"
down_revision = "0032_project_spend_policies"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "billing_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("chain_id", sa.Integer(), nullable=False),
        sa.Column("tx_hash", sa.String(length=66), nullable=False),
        sa.Column("log_index", sa.Integer(), nullable=False),
        sa.Column("block_number", sa.BigInteger(), nullable=False),
        sa.Column("from_address", sa.String(length=42), nullable=False),
        sa.Column("to_address", sa.String(length=42), nullable=False),
        sa.Column("amount_micro_usdc", sa.BigInteger(), nullable=False),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("projects.id"), nullable=True),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("chain_id", "tx_hash", "log_index", name="uq_billing_event"),
    )
    op.create_index("ix_billing_events_project", "billing_events", ["project_id", "created_at"])
    op.create_index("ix_billing_events_to", "billing_events", ["chain_id", "to_address", "block_number"])


def downgrade() -> None:
    op.drop_index("ix_billing_events_to", table_name="billing_events")
    op.drop_index("ix_billing_events_project", table_name="billing_events")
    op.drop_table("billing_events")

