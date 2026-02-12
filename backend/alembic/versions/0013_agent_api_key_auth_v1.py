"""agent api key auth v1 hardening

Revision ID: 0013_agent_api_key_auth_v1
Revises: 0012_dividend_payout_idempotency
Create Date: 2026-02-12 00:00:00.000000

"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "0013_agent_api_key_auth_v1"
down_revision = "0012_dividend_payout_idempotency"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column("agents", "api_key_hash", existing_type=sa.String(length=255), nullable=False)
    op.alter_column("agents", "api_key_last4", existing_type=sa.String(length=4), nullable=False)


def downgrade() -> None:
    # The v1 auth hardening keeps existing schema guarantees; no-op downgrade.
    pass
