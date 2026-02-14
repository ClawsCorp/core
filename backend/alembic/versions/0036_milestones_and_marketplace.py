"""milestones and marketplace generator support

Revision ID: 0036
Revises: 0035
Create Date: 2026-02-14
"""

from alembic import op
import sqlalchemy as sa


revision = "0036"
down_revision = "0035"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "milestones",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("milestone_id", sa.String(length=64), nullable=False),
        sa.Column("idempotency_key", sa.String(length=255), nullable=True),
        sa.Column("proposal_id", sa.Integer(), sa.ForeignKey("proposals.id"), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("description_md", sa.Text(), nullable=True),
        sa.Column("status", sa.Enum("planned", "in_progress", "done", name="milestone_status"), nullable=False),
        sa.Column("priority", sa.String(length=16), nullable=True),
        sa.Column("deadline_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
    )
    op.create_index("ix_milestones_milestone_id", "milestones", ["milestone_id"], unique=True)
    op.create_index("ix_milestones_idempotency_key", "milestones", ["idempotency_key"], unique=True)
    op.create_index("ix_milestones_proposal_id", "milestones", ["proposal_id"], unique=False)

    op.add_column("bounties", sa.Column("origin_milestone_id", sa.String(length=64), nullable=True))
    op.create_index("ix_bounties_origin_milestone_id", "bounties", ["origin_milestone_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_bounties_origin_milestone_id", table_name="bounties")
    op.drop_column("bounties", "origin_milestone_id")

    op.drop_index("ix_milestones_proposal_id", table_name="milestones")
    op.drop_index("ix_milestones_idempotency_key", table_name="milestones")
    op.drop_index("ix_milestones_milestone_id", table_name="milestones")
    op.drop_table("milestones")
    op.execute("DROP TYPE IF EXISTS milestone_status")
