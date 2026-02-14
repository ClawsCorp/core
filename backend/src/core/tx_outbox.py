from __future__ import annotations

import json
import secrets

from sqlalchemy.orm import Session

from src.core.db_utils import insert_or_get_by_unique
from src.models.tx_outbox import TxOutbox


def new_tx_outbox_task_id(db: Session) -> str:
    for _ in range(5):
        candidate = f"txo_{secrets.token_hex(8)}"
        exists = db.query(TxOutbox.id).filter(TxOutbox.task_id == candidate).first()
        if not exists:
            return candidate
    raise RuntimeError("Failed to generate unique tx outbox task id")


def enqueue_tx_outbox_task(
    db: Session,
    *,
    task_type: str,
    payload: dict,
    idempotency_key: str | None,
) -> TxOutbox:
    row = TxOutbox(
        task_id=new_tx_outbox_task_id(db),
        idempotency_key=idempotency_key,
        task_type=task_type,
        payload_json=json.dumps(payload, separators=(",", ":"), sort_keys=True),
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
            model=TxOutbox,
            unique_filter={"idempotency_key": idempotency_key},
        )
    else:
        db.add(row)
        db.flush()

    return row

