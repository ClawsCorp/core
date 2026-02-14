"""project funding rounds + deposits

Revision ID: 0038
Revises: 0037
Create Date: 2026-02-14
"""

from alembic import op
import sqlalchemy as sa


revision = "0038"
down_revision = "0037"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "project_funding_rounds",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("round_id", sa.String(length=64), nullable=False),
        sa.Column("idempotency_key", sa.String(length=255), nullable=False),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=True),
        sa.Column("status", sa.String(length=16), server_default="open", nullable=False),
        sa.Column("cap_micro_usdc", sa.BigInteger(), nullable=True),
        sa.Column("opened_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("round_id", name="uq_project_funding_rounds_round_id"),
        sa.UniqueConstraint("idempotency_key", name="uq_project_funding_rounds_idempotency_key"),
    )
    op.create_index("ix_project_funding_rounds_round_id", "project_funding_rounds", ["round_id"])
    op.create_index("ix_project_funding_rounds_project_id", "project_funding_rounds", ["project_id"])
    op.create_index("ix_project_funding_rounds_status", "project_funding_rounds", ["status"])

    op.create_table(
        "project_funding_deposits",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("deposit_id", sa.String(length=64), nullable=False),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("funding_round_id", sa.Integer(), sa.ForeignKey("project_funding_rounds.id"), nullable=True),
        sa.Column("observed_transfer_id", sa.Integer(), sa.ForeignKey("observed_usdc_transfers.id"), nullable=False),
        sa.Column("chain_id", sa.Integer(), nullable=False),
        sa.Column("from_address", sa.String(length=42), nullable=False),
        sa.Column("to_address", sa.String(length=42), nullable=False),
        sa.Column("amount_micro_usdc", sa.BigInteger(), nullable=False),
        sa.Column("block_number", sa.BigInteger(), nullable=False),
        sa.Column("tx_hash", sa.String(length=66), nullable=False),
        sa.Column("log_index", sa.Integer(), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint(
            "observed_transfer_id",
            name="uq_project_funding_deposits_observed_transfer_id",
        ),
        sa.UniqueConstraint("deposit_id", name="uq_project_funding_deposits_deposit_id"),
    )
    op.create_index("ix_project_funding_deposits_deposit_id", "project_funding_deposits", ["deposit_id"])
    op.create_index("ix_project_funding_deposits_project_id", "project_funding_deposits", ["project_id"])
    op.create_index("ix_project_funding_deposits_funding_round_id", "project_funding_deposits", ["funding_round_id"])
    op.create_index("ix_project_funding_deposits_chain_id", "project_funding_deposits", ["chain_id"])
    op.create_index("ix_project_funding_deposits_from_address", "project_funding_deposits", ["from_address"])
    op.create_index("ix_project_funding_deposits_to_address", "project_funding_deposits", ["to_address"])
    op.create_index("ix_project_funding_deposits_block_number", "project_funding_deposits", ["block_number"])
    op.create_index("ix_project_funding_deposits_tx_hash", "project_funding_deposits", ["tx_hash"])
    op.create_index(
        "ix_project_funding_deposits_project_round",
        "project_funding_deposits",
        ["project_id", "funding_round_id", "block_number"],
    )
    op.create_index(
        "ix_project_funding_deposits_project_from",
        "project_funding_deposits",
        ["project_id", "from_address", "block_number"],
    )


def downgrade() -> None:
    op.drop_index("ix_project_funding_deposits_project_from", table_name="project_funding_deposits")
    op.drop_index("ix_project_funding_deposits_project_round", table_name="project_funding_deposits")
    op.drop_index("ix_project_funding_deposits_tx_hash", table_name="project_funding_deposits")
    op.drop_index("ix_project_funding_deposits_block_number", table_name="project_funding_deposits")
    op.drop_index("ix_project_funding_deposits_to_address", table_name="project_funding_deposits")
    op.drop_index("ix_project_funding_deposits_from_address", table_name="project_funding_deposits")
    op.drop_index("ix_project_funding_deposits_chain_id", table_name="project_funding_deposits")
    op.drop_index("ix_project_funding_deposits_funding_round_id", table_name="project_funding_deposits")
    op.drop_index("ix_project_funding_deposits_project_id", table_name="project_funding_deposits")
    op.drop_index("ix_project_funding_deposits_deposit_id", table_name="project_funding_deposits")
    op.drop_table("project_funding_deposits")

    op.drop_index("ix_project_funding_rounds_status", table_name="project_funding_rounds")
    op.drop_index("ix_project_funding_rounds_project_id", table_name="project_funding_rounds")
    op.drop_index("ix_project_funding_rounds_round_id", table_name="project_funding_rounds")
    op.drop_table("project_funding_rounds")

