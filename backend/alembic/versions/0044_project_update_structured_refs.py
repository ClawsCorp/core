"""project update structured refs

Revision ID: 0044
Revises: 0043
Create Date: 2026-03-02
"""

from alembic import op
import sqlalchemy as sa


revision = "0044"
down_revision = "0043"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("project_updates", sa.Column("ref_kind", sa.String(length=32), nullable=True))
    op.add_column("project_updates", sa.Column("ref_url", sa.String(length=255), nullable=True))
    op.add_column("project_updates", sa.Column("tx_hash", sa.String(length=66), nullable=True))


def downgrade() -> None:
    op.drop_column("project_updates", "tx_hash")
    op.drop_column("project_updates", "ref_url")
    op.drop_column("project_updates", "ref_kind")
