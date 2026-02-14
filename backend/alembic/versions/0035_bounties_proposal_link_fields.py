"""bounties: proposal link + basic SLA fields

Revision ID: 0035
Revises: 0034_project_domains
Create Date: 2026-02-14
"""

from alembic import op
import sqlalchemy as sa


revision = "0035"
down_revision = "0034_project_domains"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("bounties", sa.Column("origin_proposal_id", sa.String(length=64), nullable=True))
    op.add_column("bounties", sa.Column("priority", sa.String(length=16), nullable=True))
    op.add_column("bounties", sa.Column("deadline_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index("ix_bounties_origin_proposal_id", "bounties", ["origin_proposal_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_bounties_origin_proposal_id", table_name="bounties")
    op.drop_column("bounties", "deadline_at")
    op.drop_column("bounties", "priority")
    op.drop_column("bounties", "origin_proposal_id")
