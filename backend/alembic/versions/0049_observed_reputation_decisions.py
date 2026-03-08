"""observed reputation decisions

Revision ID: 0049
Revises: 0048
Create Date: 2026-03-08 00:30:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0049"
down_revision = "0048"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "observed_social_signal_decisions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("decision_id", sa.String(length=64), nullable=False),
        sa.Column("decision_key", sa.String(length=255), nullable=False),
        sa.Column("observed_social_signal_id", sa.Integer(), nullable=False),
        sa.Column("decision_status", sa.String(length=24), nullable=False),
        sa.Column("reason_code", sa.String(length=64), nullable=True),
        sa.Column("identity_key", sa.String(length=128), nullable=True),
        sa.Column("reputation_event_id", sa.Integer(), nullable=True),
        sa.Column("note", sa.String(length=255), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["observed_social_signal_id"], ["observed_social_signals.id"]),
        sa.ForeignKeyConstraint(["reputation_event_id"], ["reputation_events.id"]),
        sa.UniqueConstraint("decision_id", name="uq_observed_social_signal_decisions_decision_id"),
        sa.UniqueConstraint("decision_key", name="uq_observed_social_signal_decisions_decision_key"),
    )
    op.create_index("ix_observed_social_signal_decisions_decision_id", "observed_social_signal_decisions", ["decision_id"])
    op.create_index("ix_observed_social_signal_decisions_decision_key", "observed_social_signal_decisions", ["decision_key"])
    op.create_index(
        "ix_observed_social_signal_decisions_observed_id",
        "observed_social_signal_decisions",
        ["observed_social_signal_id"],
    )
    op.create_index("ix_observed_social_signal_decisions_status", "observed_social_signal_decisions", ["decision_status"])
    op.create_index("ix_observed_social_signal_decisions_reason", "observed_social_signal_decisions", ["reason_code"])
    op.create_index(
        "ix_observed_social_signal_decisions_identity",
        "observed_social_signal_decisions",
        ["identity_key"],
    )

    op.create_table(
        "observed_customer_referral_decisions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("decision_id", sa.String(length=64), nullable=False),
        sa.Column("decision_key", sa.String(length=255), nullable=False),
        sa.Column("observed_customer_referral_id", sa.Integer(), nullable=False),
        sa.Column("decision_status", sa.String(length=24), nullable=False),
        sa.Column("reason_code", sa.String(length=64), nullable=True),
        sa.Column("identity_key", sa.String(length=128), nullable=True),
        sa.Column("reputation_event_id", sa.Integer(), nullable=True),
        sa.Column("note", sa.String(length=255), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["observed_customer_referral_id"], ["observed_customer_referrals.id"]),
        sa.ForeignKeyConstraint(["reputation_event_id"], ["reputation_events.id"]),
        sa.UniqueConstraint("decision_id", name="uq_observed_customer_referral_decisions_decision_id"),
        sa.UniqueConstraint("decision_key", name="uq_observed_customer_referral_decisions_decision_key"),
    )
    op.create_index(
        "ix_observed_customer_referral_decisions_decision_id",
        "observed_customer_referral_decisions",
        ["decision_id"],
    )
    op.create_index(
        "ix_observed_customer_referral_decisions_decision_key",
        "observed_customer_referral_decisions",
        ["decision_key"],
    )
    op.create_index(
        "ix_observed_customer_referral_decisions_observed_id",
        "observed_customer_referral_decisions",
        ["observed_customer_referral_id"],
    )
    op.create_index(
        "ix_observed_customer_referral_decisions_status",
        "observed_customer_referral_decisions",
        ["decision_status"],
    )
    op.create_index(
        "ix_observed_customer_referral_decisions_reason",
        "observed_customer_referral_decisions",
        ["reason_code"],
    )
    op.create_index(
        "ix_observed_customer_referral_decisions_identity",
        "observed_customer_referral_decisions",
        ["identity_key"],
    )


def downgrade() -> None:
    op.drop_index("ix_observed_customer_referral_decisions_identity", table_name="observed_customer_referral_decisions")
    op.drop_index("ix_observed_customer_referral_decisions_reason", table_name="observed_customer_referral_decisions")
    op.drop_index("ix_observed_customer_referral_decisions_status", table_name="observed_customer_referral_decisions")
    op.drop_index("ix_observed_customer_referral_decisions_observed_id", table_name="observed_customer_referral_decisions")
    op.drop_index("ix_observed_customer_referral_decisions_decision_key", table_name="observed_customer_referral_decisions")
    op.drop_index("ix_observed_customer_referral_decisions_decision_id", table_name="observed_customer_referral_decisions")
    op.drop_table("observed_customer_referral_decisions")

    op.drop_index("ix_observed_social_signal_decisions_identity", table_name="observed_social_signal_decisions")
    op.drop_index("ix_observed_social_signal_decisions_reason", table_name="observed_social_signal_decisions")
    op.drop_index("ix_observed_social_signal_decisions_status", table_name="observed_social_signal_decisions")
    op.drop_index("ix_observed_social_signal_decisions_observed_id", table_name="observed_social_signal_decisions")
    op.drop_index("ix_observed_social_signal_decisions_decision_key", table_name="observed_social_signal_decisions")
    op.drop_index("ix_observed_social_signal_decisions_decision_id", table_name="observed_social_signal_decisions")
    op.drop_table("observed_social_signal_decisions")
