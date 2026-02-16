# SPDX-License-Identifier: BSL-1.1

from __future__ import annotations

import json
import secrets

from sqlalchemy.orm import Session

from src.core.db_utils import insert_or_get_by_unique
from src.models.git_outbox import GitOutbox


def new_git_outbox_task_id(db: Session) -> str:
    for _ in range(5):
        candidate = f"gto_{secrets.token_hex(8)}"
        exists = db.query(GitOutbox.id).filter(GitOutbox.task_id == candidate).first()
        if not exists:
            return candidate
    raise RuntimeError("Failed to generate unique git outbox task id")


def enqueue_git_outbox_task(
    db: Session,
    *,
    task_type: str,
    payload: dict,
    idempotency_key: str | None,
    project_id: int | None = None,
    requested_by_agent_id: int | None = None,
) -> GitOutbox:
    row = GitOutbox(
        task_id=new_git_outbox_task_id(db),
        idempotency_key=idempotency_key,
        project_id=project_id,
        requested_by_agent_id=requested_by_agent_id,
        task_type=task_type,
        payload_json=json.dumps(payload, separators=(",", ":"), sort_keys=True),
        result_json=None,
        branch_name=None,
        commit_sha=None,
        status="pending",
        attempts=0,
        last_error_hint=None,
        locked_at=None,
        locked_by=None,
    )
    if idempotency_key:
        row, _created = insert_or_get_by_unique(
            db,
            instance=row,
            model=GitOutbox,
            unique_filter={"idempotency_key": idempotency_key},
        )
    else:
        db.add(row)
        db.flush()
    return row
