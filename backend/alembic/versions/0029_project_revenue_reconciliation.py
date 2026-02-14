"""project revenue reconciliation

Revision ID: 0029_project_revenue_reconciliation
Revises: 0028_observed_usdc_transfers
Create Date: 2026-02-14 00:00:00.000000

"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0029_project_revenue_reconciliation"
down_revision = "0028_observed_usdc_transfers"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("projects", sa.Column("revenue_address", sa.String(length=42), nullable=True))
    op.create_index("ix_projects_revenue_address", "projects", ["revenue_address"])

    op.create_table(
        "project_revenue_reconciliation_reports",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("revenue_address", sa.String(length=42), nullable=False),
        sa.Column("ledger_balance_micro_usdc", sa.BigInteger(), nullable=True),
        sa.Column("onchain_balance_micro_usdc", sa.BigInteger(), nullable=True),
        sa.Column("delta_micro_usdc", sa.BigInteger(), nullable=True),
        sa.Column("ready", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("blocked_reason", sa.String(length=64), nullable=True),
        sa.Column("computed_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index(
        "ix_project_revenue_recon_project_computed",
        "project_revenue_reconciliation_reports",
        ["project_id", "computed_at"],
    )
    op.create_index(
        "ix_project_revenue_recon_ready_computed",
        "project_revenue_reconciliation_reports",
        ["ready", "computed_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_project_revenue_recon_ready_computed", table_name="project_revenue_reconciliation_reports")
    op.drop_index("ix_project_revenue_recon_project_computed", table_name="project_revenue_reconciliation_reports")
    op.drop_table("project_revenue_reconciliation_reports")

    op.drop_index("ix_projects_revenue_address", table_name="projects")
    op.drop_column("projects", "revenue_address")

