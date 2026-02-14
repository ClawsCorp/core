"""add projects discussion_thread_id

Revision ID: 0025_projects_discussion_thread_id
Revises: 0024_proposals_discussion_thread_id
Create Date: 2026-02-14 00:00:00.000000

"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0025_projects_discussion_thread_id"
down_revision = "0024_proposals_discussion_thread_id"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("projects", sa.Column("discussion_thread_id", sa.String(length=64), nullable=True))
    op.create_unique_constraint(
        "uq_projects_discussion_thread_id", "projects", ["discussion_thread_id"]
    )


def downgrade() -> None:
    op.drop_constraint("uq_projects_discussion_thread_id", "projects", type_="unique")
    op.drop_column("projects", "discussion_thread_id")

