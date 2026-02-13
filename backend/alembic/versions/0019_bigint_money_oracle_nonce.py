"""bigint money fields and oracle nonce replay guard

Revision ID: 0019_bigint_money_oracle_nonce
Revises: 0018_bounty_funding_source
Create Date: 2026-02-13 00:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0019_bigint_money_oracle_nonce"
down_revision = "0018_bounty_funding_source"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Alembic's default `alembic_version.version_num` is VARCHAR(32).
    # Keep revisions <= 32 chars, and expand the column to avoid future deploy outages.
    op.alter_column(
        "alembic_version",
        "version_num",
        existing_type=sa.String(length=32),
        type_=sa.String(length=255),
        nullable=False,
    )

    op.alter_column(
        "revenue_events",
        "amount_micro_usdc",
        existing_type=sa.Integer(),
        type_=sa.BigInteger(),
        postgresql_using="amount_micro_usdc::bigint",
    )
    op.alter_column(
        "expense_events",
        "amount_micro_usdc",
        existing_type=sa.Integer(),
        type_=sa.BigInteger(),
        postgresql_using="amount_micro_usdc::bigint",
    )
    op.alter_column(
        "bounties",
        "amount_micro_usdc",
        existing_type=sa.Integer(),
        type_=sa.BigInteger(),
        postgresql_using="amount_micro_usdc::bigint",
    )
    op.alter_column(
        "projects",
        "monthly_budget_micro_usdc",
        existing_type=sa.Integer(),
        type_=sa.BigInteger(),
        postgresql_using="monthly_budget_micro_usdc::bigint",
    )
    op.alter_column(
        "settlements",
        "revenue_sum_micro_usdc",
        existing_type=sa.Integer(),
        type_=sa.BigInteger(),
        postgresql_using="revenue_sum_micro_usdc::bigint",
    )
    op.alter_column(
        "settlements",
        "expense_sum_micro_usdc",
        existing_type=sa.Integer(),
        type_=sa.BigInteger(),
        postgresql_using="expense_sum_micro_usdc::bigint",
    )
    op.alter_column(
        "settlements",
        "profit_sum_micro_usdc",
        existing_type=sa.Integer(),
        type_=sa.BigInteger(),
        postgresql_using="profit_sum_micro_usdc::bigint",
    )
    op.alter_column(
        "reconciliation_reports",
        "revenue_sum_micro_usdc",
        existing_type=sa.Integer(),
        type_=sa.BigInteger(),
        postgresql_using="revenue_sum_micro_usdc::bigint",
    )
    op.alter_column(
        "reconciliation_reports",
        "expense_sum_micro_usdc",
        existing_type=sa.Integer(),
        type_=sa.BigInteger(),
        postgresql_using="expense_sum_micro_usdc::bigint",
    )
    op.alter_column(
        "reconciliation_reports",
        "profit_sum_micro_usdc",
        existing_type=sa.Integer(),
        type_=sa.BigInteger(),
        postgresql_using="profit_sum_micro_usdc::bigint",
    )
    op.alter_column(
        "project_capital_events",
        "delta_micro_usdc",
        existing_type=sa.Integer(),
        type_=sa.BigInteger(),
        postgresql_using="delta_micro_usdc::bigint",
    )

    op.create_table(
        "oracle_nonces",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("request_id", sa.String(length=64), nullable=False),
        sa.Column("seen_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_oracle_nonces_request_id", "oracle_nonces", ["request_id"], unique=True)


def downgrade() -> None:
    op.alter_column(
        "alembic_version",
        "version_num",
        existing_type=sa.String(length=255),
        type_=sa.String(length=32),
        nullable=False,
    )

    op.drop_index("ix_oracle_nonces_request_id", table_name="oracle_nonces")
    op.drop_table("oracle_nonces")

    op.alter_column(
        "project_capital_events",
        "delta_micro_usdc",
        existing_type=sa.BigInteger(),
        type_=sa.Integer(),
        postgresql_using="delta_micro_usdc::integer",
    )
    op.alter_column(
        "reconciliation_reports",
        "profit_sum_micro_usdc",
        existing_type=sa.BigInteger(),
        type_=sa.Integer(),
        postgresql_using="profit_sum_micro_usdc::integer",
    )
    op.alter_column(
        "reconciliation_reports",
        "expense_sum_micro_usdc",
        existing_type=sa.BigInteger(),
        type_=sa.Integer(),
        postgresql_using="expense_sum_micro_usdc::integer",
    )
    op.alter_column(
        "reconciliation_reports",
        "revenue_sum_micro_usdc",
        existing_type=sa.BigInteger(),
        type_=sa.Integer(),
        postgresql_using="revenue_sum_micro_usdc::integer",
    )
    op.alter_column(
        "settlements",
        "profit_sum_micro_usdc",
        existing_type=sa.BigInteger(),
        type_=sa.Integer(),
        postgresql_using="profit_sum_micro_usdc::integer",
    )
    op.alter_column(
        "settlements",
        "expense_sum_micro_usdc",
        existing_type=sa.BigInteger(),
        type_=sa.Integer(),
        postgresql_using="expense_sum_micro_usdc::integer",
    )
    op.alter_column(
        "settlements",
        "revenue_sum_micro_usdc",
        existing_type=sa.BigInteger(),
        type_=sa.Integer(),
        postgresql_using="revenue_sum_micro_usdc::integer",
    )
    op.alter_column(
        "projects",
        "monthly_budget_micro_usdc",
        existing_type=sa.BigInteger(),
        type_=sa.Integer(),
        postgresql_using="monthly_budget_micro_usdc::integer",
    )
    op.alter_column(
        "bounties",
        "amount_micro_usdc",
        existing_type=sa.BigInteger(),
        type_=sa.Integer(),
        postgresql_using="amount_micro_usdc::integer",
    )
    op.alter_column(
        "expense_events",
        "amount_micro_usdc",
        existing_type=sa.BigInteger(),
        type_=sa.Integer(),
        postgresql_using="amount_micro_usdc::integer",
    )
    op.alter_column(
        "revenue_events",
        "amount_micro_usdc",
        existing_type=sa.BigInteger(),
        type_=sa.Integer(),
        postgresql_using="amount_micro_usdc::integer",
    )
