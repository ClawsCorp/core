#!/usr/bin/env python3
# SPDX-License-Identifier: BSL-1.1

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from sqlalchemy.orm import Session


REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = REPO_ROOT / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from src.core.config import get_settings  # noqa: E402
from src.core.database import SessionLocal  # noqa: E402
from src.models.bounty import Bounty  # noqa: E402
from src.services.bounty_git import (  # noqa: E402
    apply_bounty_git_metadata_backfill,
    bounty_needs_git_metadata_backfill,
    extract_git_pr_url,
    find_backfill_git_outbox_candidate,
)


def _find_bounty(db: Session, identifier: str) -> Bounty | None:
    candidate = str(identifier or "").strip()
    if not candidate:
        return None
    if candidate.isdigit():
        row = db.query(Bounty).filter(Bounty.id == int(candidate)).first()
        if row is not None:
            return row
    return db.query(Bounty).filter(Bounty.bounty_id == candidate).first()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bounty-id", required=True)
    parser.add_argument("--task-id")
    parser.add_argument("--task-type")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    settings = get_settings()
    if SessionLocal is None or not settings.database_url:
        print(json.dumps({"ok": False, "error": "database_not_configured"}, ensure_ascii=True))
        return 2

    with SessionLocal() as db:
        bounty = _find_bounty(db, args.bounty_id)
        if bounty is None:
            print(
                json.dumps(
                    {"ok": False, "error": "bounty_not_found", "bounty_id": args.bounty_id},
                    ensure_ascii=True,
                )
            )
            return 1

        if not args.force and not bounty_needs_git_metadata_backfill(bounty):
            print(
                json.dumps(
                    {
                        "ok": True,
                        "status": "skipped",
                        "reason": "already_has_real_git_metadata",
                        "bounty_id": bounty.bounty_id,
                        "pr_url": bounty.pr_url,
                        "merge_sha": bounty.merge_sha,
                    },
                    ensure_ascii=True,
                )
            )
            return 0

        candidate = find_backfill_git_outbox_candidate(
            db,
            bounty,
            task_id=args.task_id,
            task_type=args.task_type,
        )
        if candidate is None:
            print(
                json.dumps(
                    {
                        "ok": False,
                        "error": "git_task_not_found",
                        "bounty_id": bounty.bounty_id,
                        "task_id": args.task_id,
                        "task_type": args.task_type,
                    },
                    ensure_ascii=True,
                )
            )
            return 1

        before = {"pr_url": bounty.pr_url, "merge_sha": bounty.merge_sha}
        changed = apply_bounty_git_metadata_backfill(bounty, candidate, force=args.force)
        after = {"pr_url": bounty.pr_url, "merge_sha": bounty.merge_sha}

        if changed and not args.dry_run:
            db.commit()
        else:
            db.rollback()

        print(
            json.dumps(
                {
                    "ok": True,
                    "status": "updated" if changed and not args.dry_run else ("dry_run" if changed else "no_change"),
                    "bounty_id": bounty.bounty_id,
                    "task": {
                        "task_id": candidate.task_id,
                        "task_type": candidate.task_type,
                        "commit_sha": candidate.commit_sha,
                        "pr_url": extract_git_pr_url(candidate),
                    },
                    "before": before,
                    "after": after,
                },
                ensure_ascii=True,
            )
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
