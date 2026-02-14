"""tx outbox crash-safe fields + lock ttl support

Revision ID: 0030_tx_outbox_crash_safe
Revises: 0029_project_revenue_reconciliation
Create Date: 2026-02-14 00:00:00.000000

"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0030_tx_outbox_crash_safe"
down_revision = "0029_project_revenue_reconciliation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("tx_outbox", sa.Column("tx_hash", sa.String(length=80), nullable=True))
    op.add_column("tx_outbox", sa.Column("result_json", sa.Text(), nullable=True))
    op.create_index("ix_tx_outbox_tx_hash", "tx_outbox", ["tx_hash"])


def downgrade() -> None:
    op.drop_index("ix_tx_outbox_tx_hash", table_name="tx_outbox")
    op.drop_column("tx_outbox", "result_json")
    op.drop_column("tx_outbox", "tx_hash")

