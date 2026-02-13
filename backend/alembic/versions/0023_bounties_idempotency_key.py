"""add bounties idempotency_key

Revision ID: 0023_bounties_idempotency_key
Revises: 0022_project_treasury_and_capital_reconciliation
Create Date: 2026-02-14 00:00:00.000000

"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0023_bounties_idempotency_key"
down_revision = "0022_project_treasury_and_capital_reconciliation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("bounties", sa.Column("idempotency_key", sa.String(length=255), nullable=True))
    op.create_unique_constraint("uq_bounties_idempotency_key", "bounties", ["idempotency_key"])


def downgrade() -> None:
    op.drop_constraint("uq_bounties_idempotency_key", "bounties", type_="unique")
    op.drop_column("bounties", "idempotency_key")

