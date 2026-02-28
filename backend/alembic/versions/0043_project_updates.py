"""project updates

Revision ID: 0043
Revises: 0042
Create Date: 2026-02-28
"""

from alembic import op
import sqlalchemy as sa


revision = "0043"
down_revision = "0042"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "project_updates",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("update_id", sa.String(length=64), nullable=False),
        sa.Column("idempotency_key", sa.String(length=255), nullable=True),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("author_agent_id", sa.Integer(), sa.ForeignKey("agents.id"), nullable=True),
        sa.Column("update_type", sa.String(length=32), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("body_md", sa.Text(), nullable=True),
        sa.Column("source_kind", sa.String(length=32), nullable=True),
        sa.Column("source_ref", sa.String(length=128), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("update_id", name="uq_project_updates_update_id"),
        sa.UniqueConstraint("idempotency_key", name="uq_project_updates_idempotency_key"),
    )
    op.create_index("ix_project_updates_update_id", "project_updates", ["update_id"])
    op.create_index("ix_project_updates_project_id", "project_updates", ["project_id"])
    op.create_index("ix_project_updates_author_agent_id", "project_updates", ["author_agent_id"])
    op.create_index("ix_project_updates_update_type", "project_updates", ["update_type"])
    op.create_index("ix_project_updates_source_kind", "project_updates", ["source_kind"])
    op.create_index("ix_project_updates_source_ref", "project_updates", ["source_ref"])
    op.create_index(
        "ix_project_updates_project_created_at",
        "project_updates",
        ["project_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_project_updates_project_created_at", table_name="project_updates")
    op.drop_index("ix_project_updates_source_ref", table_name="project_updates")
    op.drop_index("ix_project_updates_source_kind", table_name="project_updates")
    op.drop_index("ix_project_updates_update_type", table_name="project_updates")
    op.drop_index("ix_project_updates_author_agent_id", table_name="project_updates")
    op.drop_index("ix_project_updates_project_id", table_name="project_updates")
    op.drop_index("ix_project_updates_update_id", table_name="project_updates")
    op.drop_table("project_updates")
