"""add proposals discussion_thread_id

Revision ID: 0024_proposals_discussion_thread_id
Revises: 0023_bounties_idempotency_key
Create Date: 2026-02-13 00:00:00.000000

"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0024_proposals_discussion_thread_id"
down_revision = "0023_bounties_idempotency_key"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("proposals", sa.Column("discussion_thread_id", sa.String(length=64), nullable=True))
    op.create_unique_constraint(
        "uq_proposals_discussion_thread_id", "proposals", ["discussion_thread_id"]
    )


def downgrade() -> None:
    op.drop_constraint("uq_proposals_discussion_thread_id", "proposals", type_="unique")
    op.drop_column("proposals", "discussion_thread_id")

