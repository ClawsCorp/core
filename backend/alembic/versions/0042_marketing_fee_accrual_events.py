"""marketing fee accrual events

Revision ID: 0042
Revises: 0041
Create Date: 2026-02-21
"""

from alembic import op
import sqlalchemy as sa


revision = "0042"
down_revision = "0041"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "marketing_fee_accrual_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("event_id", sa.String(length=64), nullable=False),
        sa.Column("idempotency_key", sa.String(length=255), nullable=False),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("projects.id"), nullable=True),
        sa.Column("profit_month_id", sa.String(length=6), nullable=True),
        sa.Column("bucket", sa.String(length=32), nullable=False),
        sa.Column("source", sa.String(length=64), nullable=False),
        sa.Column("gross_amount_micro_usdc", sa.BigInteger(), nullable=False),
        sa.Column("fee_amount_micro_usdc", sa.BigInteger(), nullable=False),
        sa.Column("chain_id", sa.Integer(), nullable=True),
        sa.Column("tx_hash", sa.String(length=255), nullable=True),
        sa.Column("log_index", sa.Integer(), nullable=True),
        sa.Column("evidence_url", sa.String(length=1024), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("gross_amount_micro_usdc > 0", name="ck_marketing_fee_accrual_gross_positive"),
        sa.CheckConstraint("fee_amount_micro_usdc > 0", name="ck_marketing_fee_accrual_fee_positive"),
        sa.UniqueConstraint("event_id", name="uq_marketing_fee_accrual_event_id"),
        sa.UniqueConstraint("idempotency_key", name="uq_marketing_fee_accrual_idempotency_key"),
    )
    op.create_index("ix_marketing_fee_accrual_event_id", "marketing_fee_accrual_events", ["event_id"])
    op.create_index("ix_marketing_fee_accrual_idempotency_key", "marketing_fee_accrual_events", ["idempotency_key"])
    op.create_index("ix_marketing_fee_accrual_project_id", "marketing_fee_accrual_events", ["project_id"])
    op.create_index("ix_marketing_fee_accrual_profit_month_id", "marketing_fee_accrual_events", ["profit_month_id"])
    op.create_index("ix_marketing_fee_accrual_bucket", "marketing_fee_accrual_events", ["bucket"])
    op.create_index("ix_marketing_fee_accrual_source", "marketing_fee_accrual_events", ["source"])
    op.create_index("ix_marketing_fee_accrual_chain_id", "marketing_fee_accrual_events", ["chain_id"])
    op.create_index("ix_marketing_fee_accrual_tx_hash", "marketing_fee_accrual_events", ["tx_hash"])


def downgrade() -> None:
    op.drop_index("ix_marketing_fee_accrual_tx_hash", table_name="marketing_fee_accrual_events")
    op.drop_index("ix_marketing_fee_accrual_chain_id", table_name="marketing_fee_accrual_events")
    op.drop_index("ix_marketing_fee_accrual_source", table_name="marketing_fee_accrual_events")
    op.drop_index("ix_marketing_fee_accrual_bucket", table_name="marketing_fee_accrual_events")
    op.drop_index("ix_marketing_fee_accrual_profit_month_id", table_name="marketing_fee_accrual_events")
    op.drop_index("ix_marketing_fee_accrual_project_id", table_name="marketing_fee_accrual_events")
    op.drop_index("ix_marketing_fee_accrual_idempotency_key", table_name="marketing_fee_accrual_events")
    op.drop_index("ix_marketing_fee_accrual_event_id", table_name="marketing_fee_accrual_events")
    op.drop_table("marketing_fee_accrual_events")
