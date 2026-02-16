"""discussion parent thread linkage

Revision ID: 0039
Revises: 0038
Create Date: 2026-02-16
"""

from alembic import op
import sqlalchemy as sa


revision = "0039"
down_revision = "0038"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "discussion_threads",
        sa.Column("parent_thread_id", sa.Integer(), nullable=True),
    )
    op.create_index(
        "ix_discussion_threads_parent_thread_id",
        "discussion_threads",
        ["parent_thread_id"],
    )
    op.create_foreign_key(
        "fk_discussion_threads_parent_thread_id",
        "discussion_threads",
        "discussion_threads",
        ["parent_thread_id"],
        ["id"],
    )


def downgrade() -> None:
    op.drop_constraint("fk_discussion_threads_parent_thread_id", "discussion_threads", type_="foreignkey")
    op.drop_index("ix_discussion_threads_parent_thread_id", table_name="discussion_threads")
    op.drop_column("discussion_threads", "parent_thread_id")
