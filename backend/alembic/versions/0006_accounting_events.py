"""add revenue and expense events

Revision ID: 0006_accounting_events
Revises: 0005_bounties
Create Date: 2024-01-06 00:00:00.000000

"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "0006_accounting_events"
down_revision = "0005_bounties"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "revenue_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("event_id", sa.String(length=64), nullable=False),
        sa.Column("profit_month_id", sa.String(length=6), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=True),
        sa.Column("amount_micro_usdc", sa.Integer(), nullable=False),
        sa.Column("tx_hash", sa.String(length=255), nullable=True),
        sa.Column("source", sa.String(length=64), nullable=False),
        sa.Column("idempotency_key", sa.String(length=255), nullable=False),
        sa.Column("evidence_url", sa.String(length=1024), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "amount_micro_usdc > 0", name="ck_revenue_events_amount_positive"
        ),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
    )
    op.create_index(
        "ix_revenue_events_event_id", "revenue_events", ["event_id"], unique=True
    )
    op.create_index(
        "ix_revenue_events_profit_month_id",
        "revenue_events",
        ["profit_month_id"],
        unique=False,
    )
    op.create_index(
        "ix_revenue_events_project_id", "revenue_events", ["project_id"], unique=False
    )
    op.create_index(
        "ix_revenue_events_idempotency_key",
        "revenue_events",
        ["idempotency_key"],
        unique=True,
    )

    op.create_table(
        "expense_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("event_id", sa.String(length=64), nullable=False),
        sa.Column("profit_month_id", sa.String(length=6), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=True),
        sa.Column("amount_micro_usdc", sa.Integer(), nullable=False),
        sa.Column("tx_hash", sa.String(length=255), nullable=True),
        sa.Column("category", sa.String(length=64), nullable=False),
        sa.Column("idempotency_key", sa.String(length=255), nullable=False),
        sa.Column("evidence_url", sa.String(length=1024), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "amount_micro_usdc > 0", name="ck_expense_events_amount_positive"
        ),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
    )
    op.create_index(
        "ix_expense_events_event_id", "expense_events", ["event_id"], unique=True
    )
    op.create_index(
        "ix_expense_events_profit_month_id",
        "expense_events",
        ["profit_month_id"],
        unique=False,
    )
    op.create_index(
        "ix_expense_events_project_id", "expense_events", ["project_id"], unique=False
    )
    op.create_index(
        "ix_expense_events_idempotency_key",
        "expense_events",
        ["idempotency_key"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("ix_expense_events_idempotency_key", table_name="expense_events")
    op.drop_index("ix_expense_events_project_id", table_name="expense_events")
    op.drop_index("ix_expense_events_profit_month_id", table_name="expense_events")
    op.drop_index("ix_expense_events_event_id", table_name="expense_events")
    op.drop_table("expense_events")

    op.drop_index("ix_revenue_events_idempotency_key", table_name="revenue_events")
    op.drop_index("ix_revenue_events_project_id", table_name="revenue_events")
    op.drop_index("ix_revenue_events_profit_month_id", table_name="revenue_events")
    op.drop_index("ix_revenue_events_event_id", table_name="revenue_events")
    op.drop_table("revenue_events")
