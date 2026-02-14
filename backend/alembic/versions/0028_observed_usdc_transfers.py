"""observed usdc transfers + indexer cursors

Revision ID: 0028_observed_usdc_transfers
Revises: 0027_tx_outbox
Create Date: 2026-02-14 00:00:00.000000

"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0028_observed_usdc_transfers"
down_revision = "0027_tx_outbox"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "indexer_cursors",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("cursor_key", sa.String(length=64), nullable=False),
        sa.Column("chain_id", sa.Integer(), nullable=False),
        sa.Column("last_block_number", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("cursor_key", "chain_id", name="uq_indexer_cursor_key_chain"),
    )
    op.create_index("ix_indexer_cursors_key_chain", "indexer_cursors", ["cursor_key", "chain_id"])

    op.create_table(
        "observed_usdc_transfers",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("chain_id", sa.Integer(), nullable=False),
        sa.Column("token_address", sa.String(length=42), nullable=False),
        sa.Column("from_address", sa.String(length=42), nullable=False),
        sa.Column("to_address", sa.String(length=42), nullable=False),
        sa.Column("amount_micro_usdc", sa.BigInteger(), nullable=False),
        sa.Column("block_number", sa.BigInteger(), nullable=False),
        sa.Column("tx_hash", sa.String(length=66), nullable=False),
        sa.Column("log_index", sa.Integer(), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("chain_id", "tx_hash", "log_index", name="uq_observed_usdc_transfer"),
    )
    op.create_index("ix_observed_usdc_transfers_block", "observed_usdc_transfers", ["chain_id", "block_number"])
    op.create_index(
        "ix_observed_usdc_transfers_to", "observed_usdc_transfers", ["chain_id", "to_address", "block_number"]
    )
    op.create_index(
        "ix_observed_usdc_transfers_from", "observed_usdc_transfers", ["chain_id", "from_address", "block_number"]
    )


def downgrade() -> None:
    op.drop_index("ix_observed_usdc_transfers_from", table_name="observed_usdc_transfers")
    op.drop_index("ix_observed_usdc_transfers_to", table_name="observed_usdc_transfers")
    op.drop_index("ix_observed_usdc_transfers_block", table_name="observed_usdc_transfers")
    op.drop_table("observed_usdc_transfers")

    op.drop_index("ix_indexer_cursors_key_chain", table_name="indexer_cursors")
    op.drop_table("indexer_cursors")

