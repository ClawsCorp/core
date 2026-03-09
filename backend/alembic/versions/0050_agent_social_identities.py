"""agent social identities

Revision ID: 0050
Revises: 0049
Create Date: 2026-03-09 00:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0050"
down_revision = "0049"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "agent_social_identities",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("identity_id", sa.String(length=64), nullable=False),
        sa.Column("agent_id", sa.Integer(), nullable=False),
        sa.Column("platform", sa.String(length=32), nullable=False),
        sa.Column("handle", sa.String(length=128), nullable=False),
        sa.Column("status", sa.String(length=16), server_default="active", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["agent_id"], ["agents.id"]),
        sa.UniqueConstraint("identity_id", name="uq_agent_social_identities_identity_id"),
    )
    op.create_index("ix_agent_social_identities_identity_id", "agent_social_identities", ["identity_id"])
    op.create_index("ix_agent_social_identities_agent_id", "agent_social_identities", ["agent_id"])
    op.create_index("ix_agent_social_identities_platform", "agent_social_identities", ["platform"])
    op.create_index("ix_agent_social_identities_handle", "agent_social_identities", ["handle"])
    op.create_index("ix_agent_social_identities_status", "agent_social_identities", ["status"])
    op.create_index(
        "uq_agent_social_identities_active_platform_handle",
        "agent_social_identities",
        ["platform", "handle"],
        unique=True,
        sqlite_where=sa.text("status = 'active'"),
        postgresql_where=sa.text("status = 'active'"),
    )


def downgrade() -> None:
    op.drop_index("uq_agent_social_identities_active_platform_handle", table_name="agent_social_identities")
    op.drop_index("ix_agent_social_identities_status", table_name="agent_social_identities")
    op.drop_index("ix_agent_social_identities_handle", table_name="agent_social_identities")
    op.drop_index("ix_agent_social_identities_platform", table_name="agent_social_identities")
    op.drop_index("ix_agent_social_identities_agent_id", table_name="agent_social_identities")
    op.drop_index("ix_agent_social_identities_identity_id", table_name="agent_social_identities")
    op.drop_table("agent_social_identities")
