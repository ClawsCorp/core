"""add project slug

Revision ID: 0021_project_slug
Revises: 0020_payout_confirm_status
Create Date: 2026-02-13 00:00:00.000000
"""

from __future__ import annotations

import re

import sqlalchemy as sa
from alembic import op


revision = "0021_project_slug"
down_revision = "0020_payout_confirm_status"
branch_labels = None
depends_on = None


def _slugify(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "-", (value or "").lower()).strip("-")
    return normalized[:48].strip("-") or "project"


def upgrade() -> None:
    op.add_column("projects", sa.Column("slug", sa.String(length=64), nullable=True))

    conn = op.get_bind()
    rows = conn.execute(sa.text("SELECT id, project_id, name FROM projects ORDER BY id ASC")).fetchall()
    seen: set[str] = set()

    for row in rows:
        base = _slugify(row.name)
        candidates = [base, f"{base}-{row.project_id[-6:]}", f"proj-{row.project_id}"]
        slug = None
        for candidate in candidates:
            if candidate not in seen:
                slug = candidate
                break
        if slug is None:
            slug = f"proj-{row.id}"
        seen.add(slug)
        conn.execute(sa.text("UPDATE projects SET slug = :slug WHERE id = :id"), {"slug": slug, "id": row.id})

    op.alter_column("projects", "slug", existing_type=sa.String(length=64), nullable=False)
    op.create_index("ix_projects_slug", "projects", ["slug"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_projects_slug", table_name="projects")
    op.drop_column("projects", "slug")
