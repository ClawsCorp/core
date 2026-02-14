"""project spend policies

Revision ID: 0032_project_spend_policies
Revises: 0031_project_settlements
Create Date: 2026-02-14
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0032_project_spend_policies"
down_revision = "0031_project_settlements"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "project_spend_policies",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("per_bounty_cap_micro_usdc", sa.BigInteger(), nullable=True),
        sa.Column("per_day_cap_micro_usdc", sa.BigInteger(), nullable=True),
        sa.Column("per_month_cap_micro_usdc", sa.BigInteger(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("project_id", name="uq_project_spend_policies_project_id"),
    )
    op.create_index("ix_project_spend_policies_project_id", "project_spend_policies", ["project_id"])


def downgrade() -> None:
    op.drop_index("ix_project_spend_policies_project_id", table_name="project_spend_policies")
    op.drop_table("project_spend_policies")

