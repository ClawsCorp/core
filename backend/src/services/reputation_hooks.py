from __future__ import annotations

import logging
from uuid import uuid4

from sqlalchemy.orm import Session

from src.core.audit import record_audit
from src.schemas.reputation import ReputationEventCreateRequest
from src.services.reputation_ingestion import ingest_reputation_event

logger = logging.getLogger(__name__)


def emit_reputation_event(
    db: Session,
    *,
    agent_id: str,
    delta_points: int,
    source: str,
    ref_type: str,
    ref_id: str,
    idempotency_key: str,
    note: str | None = None,
) -> None:
    payload = ReputationEventCreateRequest(
        event_id=str(uuid4()),
        idempotency_key=idempotency_key,
        agent_id=agent_id,
        delta_points=delta_points,
        source=source,
        ref_type=ref_type,
        ref_id=ref_id,
        note=note,
    )

    try:
        ingest_reputation_event(db, payload)
    except Exception as exc:  # non-critical hook
        logger.warning(
            "reputation hook failed source=%s ref_type=%s ref_id=%s idempotency_key=%s reason=%s",
            source,
            ref_type,
            ref_id,
            idempotency_key,
            str(exc),
        )
        return

    try:
        record_audit(
            db,
            actor_type="oracle",
            agent_id=None,
            method="INTERNAL",
            path="internal:reputation-hook",
            idempotency_key=idempotency_key,
            body_hash="internal",
            signature_status="valid",
            request_id=str(uuid4()),
        )
    except Exception as exc:  # keep hook non-critical
        logger.warning(
            "reputation hook audit failed source=%s ref_type=%s ref_id=%s idempotency_key=%s reason=%s",
            source,
            ref_type,
            ref_id,
            idempotency_key,
            str(exc),
        )
