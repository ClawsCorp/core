"""add reputation events v1

Revision ID: 0015_reputation_events_v1
Revises: 0014_discussions_mvp
Create Date: 2026-02-12 00:00:00.000000

"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "0015_reputation_events_v1"
down_revision = "0014_discussions_mvp"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "reputation_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("event_id", sa.String(length=64), nullable=False),
        sa.Column("idempotency_key", sa.String(length=255), nullable=False),
        sa.Column("agent_id", sa.Integer(), nullable=False),
        sa.Column("delta_points", sa.Integer(), nullable=False),
        sa.Column("source", sa.String(length=64), nullable=False),
        sa.Column("ref_type", sa.String(length=64), nullable=True),
        sa.Column("ref_id", sa.String(length=128), nullable=True),
        sa.Column("note", sa.String(length=255), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint("delta_points <> 0", name="ck_reputation_events_delta_nonzero"),
        sa.CheckConstraint("length(idempotency_key) > 0", name="ck_reputation_events_idempotency_nonempty"),
        sa.CheckConstraint("length(event_id) > 0", name="ck_reputation_events_event_id_nonempty"),
        sa.ForeignKeyConstraint(["agent_id"], ["agents.id"]),
        sa.UniqueConstraint("event_id", name="uq_reputation_events_event_id"),
        sa.UniqueConstraint("idempotency_key", name="uq_reputation_events_idempotency_key"),
    )

    op.create_index("ix_reputation_events_event_id", "reputation_events", ["event_id"], unique=True)
    op.create_index(
        "ix_reputation_events_idempotency_key",
        "reputation_events",
        ["idempotency_key"],
        unique=True,
    )
    op.create_index(
        "ix_reputation_events_agent_id_created_at",
        "reputation_events",
        [sa.text("agent_id"), sa.text("created_at DESC")],
    )
    op.create_index(
        "ix_reputation_events_source_created_at",
        "reputation_events",
        [sa.text("source"), sa.text("created_at DESC")],
    )


def downgrade() -> None:
    op.drop_index("ix_reputation_events_source_created_at", table_name="reputation_events")
    op.drop_index("ix_reputation_events_agent_id_created_at", table_name="reputation_events")
    op.drop_index("ix_reputation_events_idempotency_key", table_name="reputation_events")
    op.drop_index("ix_reputation_events_event_id", table_name="reputation_events")
    op.drop_table("reputation_events")
