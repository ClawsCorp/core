"""project domains

Revision ID: 0034_project_domains
Revises: 0033_billing_events
Create Date: 2026-02-14
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0034_project_domains"
down_revision = "0033_billing_events"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "project_domains",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("domain_id", sa.String(length=64), nullable=False),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("domain", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=16), server_default="pending", nullable=False),
        sa.Column("dns_txt_token", sa.String(length=128), nullable=False),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_checked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_check_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("domain_id", name="uq_project_domains_domain_id"),
        sa.UniqueConstraint("domain", name="uq_project_domains_domain"),
    )
    op.create_index("ix_project_domains_project_id", "project_domains", ["project_id"])
    op.create_index("ix_project_domains_domain", "project_domains", ["domain"])
    op.create_index("ix_project_domains_domain_id", "project_domains", ["domain_id"])


def downgrade() -> None:
    op.drop_index("ix_project_domains_domain_id", table_name="project_domains")
    op.drop_index("ix_project_domains_domain", table_name="project_domains")
    op.drop_index("ix_project_domains_project_id", table_name="project_domains")
    op.drop_table("project_domains")
