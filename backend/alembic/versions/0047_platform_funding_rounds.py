"""platform funding rounds

Revision ID: 0047
Revises: 0046
Create Date: 2026-03-04 00:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0047"
down_revision = "0046"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "platform_funding_rounds",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("round_id", sa.String(length=64), nullable=False),
        sa.Column("idempotency_key", sa.String(length=255), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=True),
        sa.Column("status", sa.String(length=16), server_default="open", nullable=False),
        sa.Column("cap_micro_usdc", sa.BigInteger(), nullable=True),
        sa.Column("opened_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("round_id", name="uq_platform_funding_rounds_round_id"),
        sa.UniqueConstraint("idempotency_key", name="uq_platform_funding_rounds_idempotency_key"),
    )
    op.create_index("ix_platform_funding_rounds_round_id", "platform_funding_rounds", ["round_id"])
    op.create_index("ix_platform_funding_rounds_status", "platform_funding_rounds", ["status"])

    op.create_table(
        "platform_funding_deposits",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("deposit_id", sa.String(length=64), nullable=False),
        sa.Column("funding_round_id", sa.Integer(), nullable=True),
        sa.Column("observed_transfer_id", sa.Integer(), nullable=False),
        sa.Column("chain_id", sa.Integer(), nullable=False),
        sa.Column("from_address", sa.String(length=42), nullable=False),
        sa.Column("to_address", sa.String(length=42), nullable=False),
        sa.Column("amount_micro_usdc", sa.BigInteger(), nullable=False),
        sa.Column("block_number", sa.BigInteger(), nullable=False),
        sa.Column("tx_hash", sa.String(length=66), nullable=False),
        sa.Column("log_index", sa.Integer(), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["funding_round_id"], ["platform_funding_rounds.id"]),
        sa.ForeignKeyConstraint(["observed_transfer_id"], ["observed_usdc_transfers.id"]),
        sa.UniqueConstraint("deposit_id"),
        sa.UniqueConstraint("observed_transfer_id", name="uq_platform_funding_deposits_observed_transfer_id"),
    )
    op.create_index("ix_platform_funding_deposits_deposit_id", "platform_funding_deposits", ["deposit_id"])
    op.create_index("ix_platform_funding_deposits_chain_id", "platform_funding_deposits", ["chain_id"])
    op.create_index("ix_platform_funding_deposits_from_address", "platform_funding_deposits", ["from_address"])
    op.create_index("ix_platform_funding_deposits_to_address", "platform_funding_deposits", ["to_address"])
    op.create_index("ix_platform_funding_deposits_block_number", "platform_funding_deposits", ["block_number"])
    op.create_index("ix_platform_funding_deposits_tx_hash", "platform_funding_deposits", ["tx_hash"])
    op.create_index("ix_platform_funding_deposits_funding_round_id", "platform_funding_deposits", ["funding_round_id"])
    op.create_index(
        "ix_platform_funding_deposits_round",
        "platform_funding_deposits",
        ["funding_round_id", "block_number"],
    )
    op.create_index(
        "ix_platform_funding_deposits_from",
        "platform_funding_deposits",
        ["from_address", "block_number"],
    )


def downgrade() -> None:
    op.drop_index("ix_platform_funding_deposits_from", table_name="platform_funding_deposits")
    op.drop_index("ix_platform_funding_deposits_round", table_name="platform_funding_deposits")
    op.drop_index("ix_platform_funding_deposits_funding_round_id", table_name="platform_funding_deposits")
    op.drop_index("ix_platform_funding_deposits_tx_hash", table_name="platform_funding_deposits")
    op.drop_index("ix_platform_funding_deposits_block_number", table_name="platform_funding_deposits")
    op.drop_index("ix_platform_funding_deposits_to_address", table_name="platform_funding_deposits")
    op.drop_index("ix_platform_funding_deposits_from_address", table_name="platform_funding_deposits")
    op.drop_index("ix_platform_funding_deposits_chain_id", table_name="platform_funding_deposits")
    op.drop_index("ix_platform_funding_deposits_deposit_id", table_name="platform_funding_deposits")
    op.drop_table("platform_funding_deposits")

    op.drop_index("ix_platform_funding_rounds_status", table_name="platform_funding_rounds")
    op.drop_index("ix_platform_funding_rounds_round_id", table_name="platform_funding_rounds")
    op.drop_table("platform_funding_rounds")
