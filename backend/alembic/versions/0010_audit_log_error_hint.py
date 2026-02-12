"""add error_hint to audit logs

Revision ID: 0010_audit_log_error_hint
Revises: 0009_distribution_creations
Create Date: 2026-02-12 00:00:00.000000

"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "0010_audit_log_error_hint"
down_revision = "0009_distribution_creations"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("audit_logs", sa.Column("error_hint", sa.String(length=255), nullable=True))


def downgrade() -> None:
    op.drop_column("audit_logs", "error_hint")
