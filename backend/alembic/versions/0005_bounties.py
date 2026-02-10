"""add bounties

Revision ID: 0005_bounties
Revises: 0004_projects
Create Date: 2024-01-05 00:00:00.000000

"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "0005_bounties"
down_revision = "0004_projects"
branch_labels = None
depends_on = None

# Use an explicit Postgres ENUM so we can create it with checkfirst=True.
# This makes the migration resilient if a previous failed attempt already created the type.
bounty_status_enum = postgresql.ENUM(
    "open",
    "claimed",
    "submitted",
    "eligible_for_payout",
    "paid",
    name="bounty_status",
    create_type=False,
)


def upgrade() -> None:
    bind = op.get_bind()
    bounty_status_enum.create(bind, checkfirst=True)

    op.create_table(
        "bounties",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("bounty_id", sa.String(length=64), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("description_md", sa.Text(), nullable=True),
        sa.Column("amount_micro_usdc", sa.Integer(), nullable=False),
        sa.Column("status", bounty_status_enum, nullable=False),
        sa.Column("claimant_agent_id", sa.Integer(), nullable=True),
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("pr_url", sa.String(length=1024), nullable=True),
        sa.Column("merge_sha", sa.String(length=64), nullable=True),
        sa.Column("paid_tx_hash", sa.String(length=255), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "amount_micro_usdc >= 0", name="ck_bounties_amount_nonneg"
        ),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.ForeignKeyConstraint(["claimant_agent_id"], ["agents.id"]),
    )
    op.create_index("ix_bounties_bounty_id", "bounties", ["bounty_id"], unique=True)
    op.create_index("ix_bounties_project_id", "bounties", ["project_id"])
    op.create_index("ix_bounties_claimant_agent_id", "bounties", ["claimant_agent_id"])


def downgrade() -> None:
    op.drop_index("ix_bounties_claimant_agent_id", table_name="bounties")
    op.drop_index("ix_bounties_project_id", table_name="bounties")
    op.drop_index("ix_bounties_bounty_id", table_name="bounties")
    op.drop_table("bounties")

    bind = op.get_bind()
    bounty_status_enum.drop(bind, checkfirst=True)
