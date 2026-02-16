"""git_outbox project and requester refs

Revision ID: 0041
Revises: 0040
Create Date: 2026-02-16
"""

from alembic import op
import sqlalchemy as sa


revision = "0041"
down_revision = "0040"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("git_outbox", sa.Column("project_id", sa.Integer(), sa.ForeignKey("projects.id"), nullable=True))
    op.add_column("git_outbox", sa.Column("requested_by_agent_id", sa.Integer(), sa.ForeignKey("agents.id"), nullable=True))
    op.create_index("ix_git_outbox_project_id", "git_outbox", ["project_id"])
    op.create_index("ix_git_outbox_requested_by_agent_id", "git_outbox", ["requested_by_agent_id"])


def downgrade() -> None:
    op.drop_index("ix_git_outbox_requested_by_agent_id", table_name="git_outbox")
    op.drop_index("ix_git_outbox_project_id", table_name="git_outbox")
    op.drop_column("git_outbox", "requested_by_agent_id")
    op.drop_column("git_outbox", "project_id")
