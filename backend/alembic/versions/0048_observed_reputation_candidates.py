"""observed reputation candidates

Revision ID: 0048
Revises: 0047
Create Date: 2026-03-08 00:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0048"
down_revision = "0047"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "observed_social_signals",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("signal_id", sa.String(length=64), nullable=False),
        sa.Column("idempotency_key", sa.String(length=255), nullable=False),
        sa.Column("agent_id", sa.Integer(), nullable=True),
        sa.Column("platform", sa.String(length=64), nullable=False),
        sa.Column("signal_url", sa.String(length=255), nullable=True),
        sa.Column("account_handle", sa.String(length=128), nullable=True),
        sa.Column("content_hash", sa.String(length=64), nullable=True),
        sa.Column("note", sa.String(length=255), nullable=True),
        sa.Column("observed_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["agent_id"], ["agents.id"]),
        sa.UniqueConstraint("signal_id", name="uq_observed_social_signals_signal_id"),
        sa.UniqueConstraint("idempotency_key", name="uq_observed_social_signals_idempotency_key"),
    )
    op.create_index("ix_observed_social_signals_signal_id", "observed_social_signals", ["signal_id"])
    op.create_index("ix_observed_social_signals_idempotency_key", "observed_social_signals", ["idempotency_key"])
    op.create_index("ix_observed_social_signals_content_hash", "observed_social_signals", ["content_hash"])

    op.create_table(
        "observed_customer_referrals",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("referral_event_id", sa.String(length=64), nullable=False),
        sa.Column("idempotency_key", sa.String(length=255), nullable=False),
        sa.Column("agent_id", sa.Integer(), nullable=True),
        sa.Column("source_system", sa.String(length=64), nullable=False),
        sa.Column("external_ref", sa.String(length=128), nullable=False),
        sa.Column("stage", sa.String(length=32), nullable=False),
        sa.Column("evidence_url", sa.String(length=255), nullable=True),
        sa.Column("note", sa.String(length=255), nullable=True),
        sa.Column("observed_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["agent_id"], ["agents.id"]),
        sa.UniqueConstraint("referral_event_id", name="uq_observed_customer_referrals_referral_event_id"),
        sa.UniqueConstraint("idempotency_key", name="uq_observed_customer_referrals_idempotency_key"),
    )
    op.create_index(
        "ix_observed_customer_referrals_referral_event_id",
        "observed_customer_referrals",
        ["referral_event_id"],
    )
    op.create_index(
        "ix_observed_customer_referrals_idempotency_key",
        "observed_customer_referrals",
        ["idempotency_key"],
    )
    op.create_index(
        "ix_observed_customer_referrals_external_ref",
        "observed_customer_referrals",
        ["external_ref"],
    )


def downgrade() -> None:
    op.drop_index("ix_observed_customer_referrals_external_ref", table_name="observed_customer_referrals")
    op.drop_index("ix_observed_customer_referrals_idempotency_key", table_name="observed_customer_referrals")
    op.drop_index("ix_observed_customer_referrals_referral_event_id", table_name="observed_customer_referrals")
    op.drop_table("observed_customer_referrals")

    op.drop_index("ix_observed_social_signals_content_hash", table_name="observed_social_signals")
    op.drop_index("ix_observed_social_signals_idempotency_key", table_name="observed_social_signals")
    op.drop_index("ix_observed_social_signals_signal_id", table_name="observed_social_signals")
    op.drop_table("observed_social_signals")
