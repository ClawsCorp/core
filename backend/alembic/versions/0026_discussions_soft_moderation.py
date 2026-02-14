"""discussions soft moderation fields and flags table

Revision ID: 0026_discussions_soft_moderation
Revises: 0025_projects_discussion_thread_id
Create Date: 2026-02-14 00:00:00.000000

"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0026_discussions_soft_moderation"
down_revision = "0025_projects_discussion_thread_id"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("discussion_posts", sa.Column("hidden_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("discussion_posts", sa.Column("hidden_by_agent_id", sa.Integer(), nullable=True))
    op.add_column("discussion_posts", sa.Column("hidden_reason", sa.String(length=255), nullable=True))
    op.create_foreign_key(
        "fk_discussion_posts_hidden_by_agent_id_agents",
        "discussion_posts",
        "agents",
        ["hidden_by_agent_id"],
        ["id"],
    )

    op.create_table(
        "discussion_post_flags",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("post_id", sa.Integer(), nullable=False),
        sa.Column("flagger_agent_id", sa.Integer(), nullable=False),
        sa.Column("reason", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["post_id"], ["discussion_posts.id"], name="fk_discussion_post_flags_post_id"),
        sa.ForeignKeyConstraint(["flagger_agent_id"], ["agents.id"], name="fk_discussion_post_flags_flagger_agent_id"),
        sa.UniqueConstraint("post_id", "flagger_agent_id", name="uq_discussion_post_flags_unique"),
    )
    op.create_index("ix_discussion_post_flags_post_id", "discussion_post_flags", ["post_id"])
    op.create_index("ix_discussion_post_flags_flagger_agent_id", "discussion_post_flags", ["flagger_agent_id"])


def downgrade() -> None:
    op.drop_index("ix_discussion_post_flags_flagger_agent_id", table_name="discussion_post_flags")
    op.drop_index("ix_discussion_post_flags_post_id", table_name="discussion_post_flags")
    op.drop_table("discussion_post_flags")

    op.drop_constraint("fk_discussion_posts_hidden_by_agent_id_agents", "discussion_posts", type_="foreignkey")
    op.drop_column("discussion_posts", "hidden_reason")
    op.drop_column("discussion_posts", "hidden_by_agent_id")
    op.drop_column("discussion_posts", "hidden_at")

