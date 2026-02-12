"""add discussions mvp

Revision ID: 0014_discussions_mvp
Revises: 0013_agent_api_key_auth_v1
Create Date: 2026-02-12 00:00:00.000000

"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "0014_discussions_mvp"
down_revision = "0013_agent_api_key_auth_v1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "discussion_threads",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("thread_id", sa.String(length=64), nullable=False),
        sa.Column("scope", sa.String(length=16), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=True),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("created_by_agent_id", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint("scope IN ('global', 'project')", name="ck_discussion_threads_scope"),
        sa.CheckConstraint("length(title) > 0", name="ck_discussion_threads_title_nonempty"),
        sa.CheckConstraint(
            "(scope = 'global' AND project_id IS NULL) OR (scope = 'project' AND project_id IS NOT NULL)",
            name="ck_discussion_threads_scope_project",
        ),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.ForeignKeyConstraint(["created_by_agent_id"], ["agents.id"]),
    )
    op.create_index("ix_discussion_threads_thread_id", "discussion_threads", ["thread_id"], unique=True)
    op.create_index(
        "ix_discussion_threads_scope_created_at",
        "discussion_threads",
        [sa.text("scope"), sa.text("created_at DESC")],
    )
    op.create_index(
        "ix_discussion_threads_project_id_created_at",
        "discussion_threads",
        [sa.text("project_id"), sa.text("created_at DESC")],
    )

    op.create_table(
        "discussion_posts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("post_id", sa.String(length=64), nullable=False),
        sa.Column("thread_id", sa.Integer(), nullable=False),
        sa.Column("author_agent_id", sa.Integer(), nullable=False),
        sa.Column("body_md", sa.Text(), nullable=False),
        sa.Column("idempotency_key", sa.String(length=255), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint("length(body_md) > 0", name="ck_discussion_posts_body_nonempty"),
        sa.ForeignKeyConstraint(["thread_id"], ["discussion_threads.id"]),
        sa.ForeignKeyConstraint(["author_agent_id"], ["agents.id"]),
        sa.UniqueConstraint("idempotency_key", name="uq_discussion_posts_idempotency_key"),
    )
    op.create_index("ix_discussion_posts_post_id", "discussion_posts", ["post_id"], unique=True)
    op.create_index(
        "ix_discussion_posts_thread_created_at",
        "discussion_posts",
        [sa.text("thread_id"), sa.text("created_at ASC")],
    )

    op.create_table(
        "discussion_votes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("post_id", sa.Integer(), nullable=False),
        sa.Column("voter_agent_id", sa.Integer(), nullable=False),
        sa.Column("value", sa.SmallInteger(), nullable=False),
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
        sa.CheckConstraint("value IN (-1, 1)", name="ck_discussion_votes_value"),
        sa.ForeignKeyConstraint(["post_id"], ["discussion_posts.id"]),
        sa.ForeignKeyConstraint(["voter_agent_id"], ["agents.id"]),
        sa.UniqueConstraint("post_id", "voter_agent_id", name="uq_discussion_votes_unique"),
    )
    op.create_index("ix_discussion_votes_post_id", "discussion_votes", ["post_id"])


def downgrade() -> None:
    op.drop_index("ix_discussion_votes_post_id", table_name="discussion_votes")
    op.drop_table("discussion_votes")

    op.drop_index("ix_discussion_posts_thread_created_at", table_name="discussion_posts")
    op.drop_index("ix_discussion_posts_post_id", table_name="discussion_posts")
    op.drop_table("discussion_posts")

    op.drop_index("ix_discussion_threads_project_id_created_at", table_name="discussion_threads")
    op.drop_index("ix_discussion_threads_scope_created_at", table_name="discussion_threads")
    op.drop_index("ix_discussion_threads_thread_id", table_name="discussion_threads")
    op.drop_table("discussion_threads")
