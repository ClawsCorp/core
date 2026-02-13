"""add bounty funding source policy

Revision ID: 0018_bounty_funding_source
Revises: 0017_project_activation_and_capital
Create Date: 2026-02-13 00:00:00.000000

"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision = "0018_bounty_funding_source"
down_revision = "0017_project_activation_and_capital"
branch_labels = None
depends_on = None


bounty_funding_source_enum = postgresql.ENUM(
    "project_capital",
    "project_revenue",
    "platform_treasury",
    name="bounty_funding_source",
    create_type=False,
)


def upgrade() -> None:
    bind = op.get_bind()
    bounty_funding_source_enum.create(bind, checkfirst=True)

    op.add_column(
        "bounties",
        sa.Column(
            "funding_source",
            bounty_funding_source_enum,
            nullable=False,
            server_default="platform_treasury",
        ),
    )

    op.execute(
        """
        UPDATE bounties
        SET funding_source = 'project_capital'
        WHERE project_id IS NOT NULL
        """
    )
    op.execute(
        """
        UPDATE bounties
        SET funding_source = 'platform_treasury'
        WHERE project_id IS NULL
        """
    )


def downgrade() -> None:
    op.drop_column("bounties", "funding_source")

    bind = op.get_bind()
    bounty_funding_source_enum.drop(bind, checkfirst=True)
