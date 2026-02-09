"""add projects and project members

Revision ID: 0004_projects
Revises: 0003_proposals_votes_reputation
Create Date: 2024-01-04 00:00:00.000000

"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "0004_projects"
down_revision = "0003_proposals_votes_reputation"
branch_labels = None
depends_on = None

project_status_enum = sa.Enum(
    "draft", "active", "paused", "archived", name="project_status"
)
project_member_role_enum = sa.Enum(
    "owner", "maintainer", "contributor", name="project_member_role"
)


def upgrade() -> None:
    op.create_table(
        "projects",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("project_id", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description_md", sa.Text(), nullable=True),
        sa.Column("status", project_status_enum, nullable=False),
        sa.Column("proposal_id", sa.String(length=64), nullable=True),
        sa.Column("treasury_wallet_address", sa.String(length=255), nullable=True),
        sa.Column("revenue_wallet_address", sa.String(length=255), nullable=True),
        sa.Column("monthly_budget_micro_usdc", sa.Integer(), nullable=True),
        sa.Column("created_by_agent_id", sa.Integer(), nullable=True),
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
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["created_by_agent_id"], ["agents.id"]),
    )
    op.create_index("ix_projects_project_id", "projects", ["project_id"], unique=True)
    op.create_index(
        "ix_projects_created_by_agent_id", "projects", ["created_by_agent_id"]
    )
    op.create_index("ix_projects_proposal_id", "projects", ["proposal_id"])

    op.create_table(
        "project_members",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("agent_id", sa.Integer(), nullable=False),
        sa.Column("role", project_member_role_enum, nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.ForeignKeyConstraint(["agent_id"], ["agents.id"]),
        sa.UniqueConstraint(
            "project_id", "agent_id", name="uq_project_members_unique"
        ),
    )
    op.create_index("ix_project_members_project_id", "project_members", ["project_id"])
    op.create_index("ix_project_members_agent_id", "project_members", ["agent_id"])


def downgrade() -> None:
    op.drop_index("ix_project_members_agent_id", table_name="project_members")
    op.drop_index("ix_project_members_project_id", table_name="project_members")
    op.drop_table("project_members")

    op.drop_index("ix_projects_proposal_id", table_name="projects")
    op.drop_index("ix_projects_created_by_agent_id", table_name="projects")
    op.drop_index("ix_projects_project_id", table_name="projects")
    op.drop_table("projects")

    bind = op.get_bind()
    project_member_role_enum.drop(bind, checkfirst=True)
    project_status_enum.drop(bind, checkfirst=True)
