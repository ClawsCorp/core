#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from sqlalchemy.orm import Session

BACKEND_DIR = Path(__file__).resolve().parents[1] / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from src.core.database import SessionLocal  # noqa: E402
from src.models.project import Project  # noqa: E402
from src.models.project_update import ProjectUpdate  # noqa: E402
from src.services.project_updates import populate_project_update_structured_refs  # noqa: E402


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Backfill structured refs for legacy project_updates rows.")
    parser.add_argument("--project-id", help="Limit backfill to one public project_id.", default=None)
    parser.add_argument("--apply", action="store_true", help="Persist changes. Default is dry-run.")
    return parser.parse_args()


def _run(db: Session, *, project_public_id: str | None, apply: bool) -> int:
    query = db.query(ProjectUpdate, Project).join(Project, Project.id == ProjectUpdate.project_id)
    if project_public_id:
        query = query.filter(Project.project_id == project_public_id)

    scanned = 0
    changed = 0
    for row, project in query.order_by(ProjectUpdate.created_at.asc(), ProjectUpdate.id.asc()).all():
        scanned += 1
        if populate_project_update_structured_refs(
            project_public_id=project.project_id,
            discussion_thread_id=project.discussion_thread_id,
            row=row,
        ):
            changed += 1
            if not apply:
                db.expire(row)

    if apply:
        db.commit()
    else:
        db.rollback()

    print(
        {
            "success": True,
            "mode": "apply" if apply else "dry_run",
            "scanned": scanned,
            "changed": changed,
            "project_id": project_public_id,
        }
    )
    return 0


def main() -> int:
    args = _parse_args()
    if not os.getenv("DATABASE_URL"):
        print({"success": False, "detail": "DATABASE_URL is required"}, file=sys.stderr)
        return 1
    db = SessionLocal()
    try:
        return _run(db, project_public_id=args.project_id, apply=bool(args.apply))
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
