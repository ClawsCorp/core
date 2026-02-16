"""crypto invoices + git outbox

Revision ID: 0040
Revises: 0039
Create Date: 2026-02-16
"""

from alembic import op
import sqlalchemy as sa


revision = "0040"
down_revision = "0039"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "project_crypto_invoices",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("invoice_id", sa.String(length=64), nullable=False),
        sa.Column("idempotency_key", sa.String(length=255), nullable=True),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("creator_agent_id", sa.Integer(), sa.ForeignKey("agents.id"), nullable=True),
        sa.Column("chain_id", sa.Integer(), nullable=False),
        sa.Column("token_address", sa.String(length=42), nullable=True),
        sa.Column("payment_address", sa.String(length=42), nullable=False),
        sa.Column("payer_address", sa.String(length=42), nullable=True),
        sa.Column("amount_micro_usdc", sa.BigInteger(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("observed_transfer_id", sa.Integer(), sa.ForeignKey("observed_usdc_transfers.id"), nullable=True),
        sa.Column("paid_tx_hash", sa.String(length=66), nullable=True),
        sa.Column("paid_log_index", sa.Integer(), nullable=True),
        sa.Column("paid_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("invoice_id", name="uq_project_crypto_invoices_invoice_id"),
        sa.UniqueConstraint("idempotency_key", name="uq_project_crypto_invoices_idempotency_key"),
        sa.UniqueConstraint("observed_transfer_id", name="uq_project_crypto_invoices_observed_transfer_id"),
    )
    op.create_index("ix_project_crypto_invoices_invoice_id", "project_crypto_invoices", ["invoice_id"])
    op.create_index("ix_project_crypto_invoices_project_id", "project_crypto_invoices", ["project_id"])
    op.create_index("ix_project_crypto_invoices_creator_agent_id", "project_crypto_invoices", ["creator_agent_id"])
    op.create_index("ix_project_crypto_invoices_status", "project_crypto_invoices", ["status"])
    op.create_index("ix_project_crypto_invoices_observed_transfer_id", "project_crypto_invoices", ["observed_transfer_id"])
    op.create_index(
        "ix_project_crypto_invoices_project_status",
        "project_crypto_invoices",
        ["project_id", "status", "created_at"],
    )

    op.create_table(
        "git_outbox",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("task_id", sa.String(length=64), nullable=False),
        sa.Column("idempotency_key", sa.String(length=255), nullable=True),
        sa.Column("task_type", sa.String(length=64), nullable=False),
        sa.Column("payload_json", sa.Text(), nullable=False),
        sa.Column("result_json", sa.Text(), nullable=True),
        sa.Column("branch_name", sa.String(length=128), nullable=True),
        sa.Column("commit_sha", sa.String(length=64), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_error_hint", sa.Text(), nullable=True),
        sa.Column("locked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("locked_by", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("task_id", name="uq_git_outbox_task_id"),
        sa.UniqueConstraint("idempotency_key", name="uq_git_outbox_idempotency_key"),
    )
    op.create_index("ix_git_outbox_task_id", "git_outbox", ["task_id"])
    op.create_index("ix_git_outbox_status", "git_outbox", ["status"])
    op.create_index("ix_git_outbox_commit_sha", "git_outbox", ["commit_sha"])


def downgrade() -> None:
    op.drop_index("ix_git_outbox_commit_sha", table_name="git_outbox")
    op.drop_index("ix_git_outbox_status", table_name="git_outbox")
    op.drop_index("ix_git_outbox_task_id", table_name="git_outbox")
    op.drop_table("git_outbox")

    op.drop_index("ix_project_crypto_invoices_project_status", table_name="project_crypto_invoices")
    op.drop_index("ix_project_crypto_invoices_observed_transfer_id", table_name="project_crypto_invoices")
    op.drop_index("ix_project_crypto_invoices_status", table_name="project_crypto_invoices")
    op.drop_index("ix_project_crypto_invoices_creator_agent_id", table_name="project_crypto_invoices")
    op.drop_index("ix_project_crypto_invoices_project_id", table_name="project_crypto_invoices")
    op.drop_index("ix_project_crypto_invoices_invoice_id", table_name="project_crypto_invoices")
    op.drop_table("project_crypto_invoices")
