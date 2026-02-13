"""add project treasury address and capital reconciliation reports

Revision ID: 0022_project_treasury_and_capital_reconciliation
Revises: 0021_project_slug
Create Date: 2026-02-13 00:00:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0022_project_treasury_and_capital_reconciliation"
down_revision = "0021_project_slug"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("projects", sa.Column("treasury_address", sa.String(length=42), nullable=True))
    op.create_index("ix_projects_treasury_address", "projects", ["treasury_address"], unique=False)

    op.create_table(
        "project_capital_reconciliation_reports",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("treasury_address", sa.String(length=42), nullable=False),
        sa.Column("ledger_balance_micro_usdc", sa.BigInteger(), nullable=True),
        sa.Column("onchain_balance_micro_usdc", sa.BigInteger(), nullable=True),
        sa.Column("delta_micro_usdc", sa.BigInteger(), nullable=True),
        sa.Column("ready", sa.Boolean(), nullable=False),
        sa.Column("blocked_reason", sa.String(length=64), nullable=True),
        sa.Column("computed_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_project_capital_recon_project_computed",
        "project_capital_reconciliation_reports",
        ["project_id", "computed_at"],
        unique=False,
    )
    op.create_index(
        "ix_project_capital_recon_ready_computed",
        "project_capital_reconciliation_reports",
        ["ready", "computed_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_project_capital_recon_ready_computed", table_name="project_capital_reconciliation_reports")
    op.drop_index("ix_project_capital_recon_project_computed", table_name="project_capital_reconciliation_reports")
    op.drop_table("project_capital_reconciliation_reports")

    op.drop_index("ix_projects_treasury_address", table_name="projects")
    op.drop_column("projects", "treasury_address")
