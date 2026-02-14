"""tx outbox skeleton

Revision ID: 0027_tx_outbox
Revises: 0026_discussions_soft_moderation
Create Date: 2026-02-14 00:00:00.000000

"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0027_tx_outbox"
down_revision = "0026_discussions_soft_moderation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "tx_outbox",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("task_id", sa.String(length=64), nullable=False),
        sa.Column("idempotency_key", sa.String(length=255), nullable=True),
        sa.Column("task_type", sa.String(length=64), nullable=False),
        sa.Column("payload_json", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column("last_error_hint", sa.Text(), nullable=True),
        sa.Column("locked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("locked_by", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("task_id", name="uq_tx_outbox_task_id"),
        sa.UniqueConstraint("idempotency_key", name="uq_tx_outbox_idempotency_key"),
    )
    op.create_index("ix_tx_outbox_task_id", "tx_outbox", ["task_id"])
    op.create_index("ix_tx_outbox_status", "tx_outbox", ["status"])


def downgrade() -> None:
    op.drop_index("ix_tx_outbox_status", table_name="tx_outbox")
    op.drop_index("ix_tx_outbox_task_id", table_name="tx_outbox")
    op.drop_table("tx_outbox")

