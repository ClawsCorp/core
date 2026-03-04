from __future__ import annotations

import logging
from uuid import uuid4

from sqlalchemy import func
from sqlalchemy.orm import Session

from src.core.audit import record_audit
from src.models.agent import Agent
from src.schemas.reputation import ReputationEventCreateRequest
from src.services.reputation_ingestion import ingest_reputation_event
from src.services.reputation_policy import calculate_project_investor_points

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


def emit_project_investor_reputation_for_wallet(
    db: Session,
    *,
    wallet_address: str | None,
    amount_micro_usdc: int,
    project_id: str,
    funding_deposit_id: str,
) -> None:
    normalized = (wallet_address or "").strip().lower()
    if not normalized:
        return

    matches = (
        db.query(Agent)
        .filter(func.lower(Agent.wallet_address) == normalized, Agent.revoked_at.is_(None))
        .order_by(Agent.id.asc())
        .limit(2)
        .all()
    )
    if len(matches) != 1:
        return

    try:
        delta_points = calculate_project_investor_points(amount_micro_usdc)
    except ValueError:
        return

    emit_reputation_event(
        db,
        agent_id=matches[0].agent_id,
        delta_points=delta_points,
        source="project_capital_contributed",
        ref_type="funding_deposit",
        ref_id=funding_deposit_id,
        idempotency_key=f"rep:project_capital_contributed:{funding_deposit_id}",
        note=f"project:{project_id};amount:{int(amount_micro_usdc)}",
    )
