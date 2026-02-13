"""project activation and project capital events

Revision ID: 0017_project_activation_capital
Revises: 0016_governance_lifecycle_fields
Create Date: 2026-02-13 00:00:00.000000

"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0017_project_activation_capital"
down_revision = "0016_governance_lifecycle_fields"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TYPE project_status ADD VALUE IF NOT EXISTS 'fundraising'")

    op.add_column("proposals", sa.Column("resulting_project_id", sa.String(length=64), nullable=True))
    op.add_column("proposals", sa.Column("activated_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index("ix_proposals_resulting_project_id", "proposals", ["resulting_project_id"], unique=False)

    op.add_column("projects", sa.Column("origin_proposal_id", sa.String(length=64), nullable=True))
    op.add_column("projects", sa.Column("originator_agent_id", sa.Integer(), nullable=True))
    op.create_index("ix_projects_origin_proposal_id", "projects", ["origin_proposal_id"], unique=True)
    op.create_index("ix_projects_originator_agent_id", "projects", ["originator_agent_id"], unique=False)
    op.create_foreign_key("fk_projects_originator_agent_id", "projects", "agents", ["originator_agent_id"], ["id"])

    op.alter_column("bounties", "project_id", existing_type=sa.Integer(), nullable=True)

    op.create_table(
        "project_capital_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("event_id", sa.String(length=64), nullable=False),
        sa.Column("idempotency_key", sa.String(length=255), nullable=False),
        sa.Column("profit_month_id", sa.String(length=6), nullable=True),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("delta_micro_usdc", sa.Integer(), nullable=False),
        sa.Column("source", sa.String(length=64), nullable=False),
        sa.Column("evidence_tx_hash", sa.String(length=255), nullable=True),
        sa.Column("evidence_url", sa.String(length=1024), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("delta_micro_usdc != 0", name="ck_project_capital_events_delta_nonzero"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
    )
    op.create_index("ix_project_capital_events_event_id", "project_capital_events", ["event_id"], unique=True)
    op.create_index("ix_project_capital_events_idempotency_key", "project_capital_events", ["idempotency_key"], unique=True)
    op.create_index("ix_project_capital_events_project_id_created_at", "project_capital_events", ["project_id", "created_at"], unique=False)
    op.create_index("ix_project_capital_events_profit_month_id_created_at", "project_capital_events", ["profit_month_id", "created_at"], unique=False)
    op.create_index("ix_project_capital_events_source_created_at", "project_capital_events", ["source", "created_at"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_project_capital_events_source_created_at", table_name="project_capital_events")
    op.drop_index("ix_project_capital_events_profit_month_id_created_at", table_name="project_capital_events")
    op.drop_index("ix_project_capital_events_project_id_created_at", table_name="project_capital_events")
    op.drop_index("ix_project_capital_events_idempotency_key", table_name="project_capital_events")
    op.drop_index("ix_project_capital_events_event_id", table_name="project_capital_events")
    op.drop_table("project_capital_events")

    op.alter_column("bounties", "project_id", existing_type=sa.Integer(), nullable=False)

    op.drop_constraint("fk_projects_originator_agent_id", "projects", type_="foreignkey")
    op.drop_index("ix_projects_originator_agent_id", table_name="projects")
    op.drop_index("ix_projects_origin_proposal_id", table_name="projects")
    op.drop_column("projects", "originator_agent_id")
    op.drop_column("projects", "origin_proposal_id")

    op.drop_index("ix_proposals_resulting_project_id", table_name="proposals")
    op.drop_column("proposals", "activated_at")
    op.drop_column("proposals", "resulting_project_id")
