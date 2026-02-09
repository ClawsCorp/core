"""add agents and audit logs

Revision ID: 0002_agents_audit_logs
Revises: 0001_initial_baseline
Create Date: 2024-01-02 00:00:00.000000

"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "0002_agents_audit_logs"
down_revision = "0001_initial_baseline"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "agents",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("agent_id", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("capabilities_json", sa.Text(), nullable=False),
        sa.Column("wallet_address", sa.String(length=255), nullable=True),
        sa.Column("api_key_hash", sa.String(length=255), nullable=False),
        sa.Column("api_key_last4", sa.String(length=4), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_agents_agent_id", "agents", ["agent_id"], unique=True)

    op.create_table(
        "audit_logs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("actor_type", sa.String(length=32), nullable=False),
        sa.Column("agent_id", sa.String(length=64), nullable=True),
        sa.Column("method", sa.String(length=16), nullable=False),
        sa.Column("path", sa.String(length=255), nullable=False),
        sa.Column("idempotency_key", sa.String(length=255), nullable=True),
        sa.Column("body_hash", sa.String(length=64), nullable=False),
        sa.Column("signature_status", sa.String(length=16), nullable=False),
        sa.Column("request_id", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_table("audit_logs")
    op.drop_index("ix_agents_agent_id", table_name="agents")
    op.drop_table("agents")
