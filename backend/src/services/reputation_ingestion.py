from __future__ import annotations

from sqlalchemy.orm import Session

from src.models.agent import Agent
from src.models.reputation_event import ReputationEvent
from src.schemas.reputation import ReputationEventCreateRequest


def ingest_reputation_event(
    db: Session,
    payload: ReputationEventCreateRequest,
) -> tuple[ReputationEvent, str]:
    if payload.delta_points == 0:
        raise ValueError("delta_points must be non-zero")

    agent = db.query(Agent).filter(Agent.agent_id == payload.agent_id).first()
    if agent is None:
        raise LookupError("Agent not found")

    existing = (
        db.query(ReputationEvent)
        .filter(ReputationEvent.idempotency_key == payload.idempotency_key)
        .first()
    )
    if existing is not None:
        return existing, agent.agent_id

    existing_by_event_id = (
        db.query(ReputationEvent).filter(ReputationEvent.event_id == payload.event_id).first()
    )
    if existing_by_event_id is not None:
        existing_agent = db.query(Agent).filter(Agent.id == existing_by_event_id.agent_id).first()
        public_agent_id = existing_agent.agent_id if existing_agent else payload.agent_id
        return existing_by_event_id, public_agent_id

    event = ReputationEvent(
        event_id=payload.event_id,
        idempotency_key=payload.idempotency_key,
        agent_id=agent.id,
        delta_points=payload.delta_points,
        source=payload.source,
        ref_type=payload.ref_type,
        ref_id=payload.ref_id,
        note=payload.note,
    )
    db.add(event)
    db.commit()
    db.refresh(event)

    return event, agent.agent_id
