"""indexer runtime state

Revision ID: 0045
Revises: 0044
Create Date: 2026-03-04
"""

from alembic import op
import sqlalchemy as sa


revision = "0045"
down_revision = "0044"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "indexer_cursors",
        sa.Column("last_scan_window_blocks", sa.Integer(), nullable=True),
    )
    op.add_column(
        "indexer_cursors",
        sa.Column("degraded_since", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "indexer_cursors",
        sa.Column("last_error_hint", sa.String(length=64), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("indexer_cursors", "last_error_hint")
    op.drop_column("indexer_cursors", "degraded_since")
    op.drop_column("indexer_cursors", "last_scan_window_blocks")
