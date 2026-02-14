"""discussion threads: ref_type/ref_id (proposal/project/bounty)

Revision ID: 0037
Revises: 0036
Create Date: 2026-02-14
"""

from alembic import op
import sqlalchemy as sa


revision = "0037"
down_revision = "0036"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("discussion_threads", sa.Column("ref_type", sa.String(length=16), nullable=True))
    op.add_column("discussion_threads", sa.Column("ref_id", sa.String(length=64), nullable=True))

    # "FK-like" integrity is enforced at the application level because the ref can point to
    # different tables (proposal/project/bounty). Here we ensure the ref fields are consistent
    # and the canonical threads cannot duplicate.
    op.create_check_constraint(
        "ck_discussion_threads_ref_consistency",
        "discussion_threads",
        "(ref_type IS NULL AND ref_id IS NULL) OR (ref_type IN ('proposal','project','bounty') AND ref_id IS NOT NULL AND length(ref_id) > 0)",
    )
    op.create_check_constraint(
        "ck_discussion_threads_ref_scope",
        "discussion_threads",
        "(ref_type IS NULL) OR "
        "(ref_type = 'proposal' AND scope = 'global' AND project_id IS NULL) OR "
        "(ref_type = 'project' AND scope = 'project' AND project_id IS NOT NULL) OR "
        "(ref_type = 'bounty')",
    )
    op.create_unique_constraint(
        "uq_discussion_threads_ref",
        "discussion_threads",
        ["ref_type", "ref_id"],
    )
    op.create_index(
        "ix_discussion_threads_ref",
        "discussion_threads",
        ["ref_type", "ref_id"],
        unique=False,
    )

    # Backfill canonical refs for existing deterministic threads linked from proposals/projects.
    op.execute(
        """
        UPDATE discussion_threads dt
        SET ref_type = 'proposal', ref_id = p.proposal_id
        FROM proposals p
        WHERE p.discussion_thread_id = dt.thread_id
          AND (dt.ref_type IS NULL AND dt.ref_id IS NULL)
        """
    )
    op.execute(
        """
        UPDATE discussion_threads dt
        SET ref_type = 'project', ref_id = pr.project_id
        FROM projects pr
        WHERE pr.discussion_thread_id = dt.thread_id
          AND (dt.ref_type IS NULL AND dt.ref_id IS NULL)
        """
    )


def downgrade() -> None:
    op.drop_index("ix_discussion_threads_ref", table_name="discussion_threads")
    op.drop_constraint("uq_discussion_threads_ref", "discussion_threads", type_="unique")
    op.drop_constraint("ck_discussion_threads_ref_scope", "discussion_threads", type_="check")
    op.drop_constraint("ck_discussion_threads_ref_consistency", "discussion_threads", type_="check")
    op.drop_column("discussion_threads", "ref_id")
    op.drop_column("discussion_threads", "ref_type")

