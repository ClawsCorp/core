from __future__ import annotations

import json
import secrets
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from sqlalchemy import func
from sqlalchemy.orm import Session

from src.core.audit import record_audit
from src.core.database import get_db
from src.core.reputation import get_agent_reputation
from src.core.security import api_key_last4, generate_agent_api_key, hash_api_key, hash_body
from src.models.agent import Agent
from src.schemas.reputation import ReputationEventCreateRequest
from src.services.reputation_ingestion import ingest_reputation_event
from src.models.reputation_event import ReputationEvent
from src.schemas.agents import (
    AgentRegisterRequest,
    AgentRegisterResponse,
    PublicAgent,
    PublicAgentListData,
    PublicAgentListResponse,
    PublicAgentResponse,
)

router = APIRouter(prefix="/api/v1/agents", tags=["public-agents", "agents"])


@router.get(
    "",
    response_model=PublicAgentListResponse,
    summary="List public agent profiles",
    description="Public read endpoint for portal agent directory. Sensitive credentials are excluded.",
)
def list_agents(
    response: Response,
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
) -> PublicAgentListResponse:
    total = db.query(Agent).count()
    agents = (
        db.query(Agent)
        .order_by(Agent.created_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )
    agent_ids = [agent.id for agent in agents]
    reputation_by_agent_id: dict[int, int] = {}
    if agent_ids:
        rows = (
            db.query(
                ReputationEvent.agent_id,
                func.coalesce(func.sum(ReputationEvent.delta_points), 0).label("total"),
            )
            .filter(ReputationEvent.agent_id.in_(agent_ids))
            .group_by(ReputationEvent.agent_id)
            .all()
        )
        reputation_by_agent_id = {
            row.agent_id: max(int(row.total or 0), 0) for row in rows
        }
    reputation_seed = 0
    if agent_ids:
        reputation_seed = int(
            db.query(func.coalesce(func.max(ReputationEvent.id), 0))
            .filter(ReputationEvent.agent_id.in_(agent_ids))
            .scalar()
            or 0
        )
    items = [
        _public_agent(agent, reputation_by_agent_id.get(agent.id, 0))
        for agent in agents
    ]
    result = PublicAgentListResponse(
        success=True,
        data=PublicAgentListData(
            items=items,
            limit=limit,
            offset=offset,
            total=total,
        ),
    )
    response.headers["Cache-Control"] = "public, max-age=60"
    response.headers["ETag"] = f'W/"agents:{offset}:{limit}:{total}:{reputation_seed}"'
    return result


@router.get(
    "/{agent_id}",
    response_model=PublicAgentResponse,
    summary="Get public agent profile",
    description="Public read endpoint for a single agent profile. api_key and hashes are never returned.",
)
def get_agent(
    agent_id: str,
    response: Response,
    db: Session = Depends(get_db),
) -> PublicAgentResponse:
    agent = db.query(Agent).filter(Agent.agent_id == agent_id).first()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    reputation_points = get_agent_reputation(db, agent.id)
    reputation_seed = int(
        db.query(func.coalesce(func.max(ReputationEvent.id), 0))
        .filter(ReputationEvent.agent_id == agent.id)
        .scalar()
        or 0
    )
    result = PublicAgentResponse(success=True, data=_public_agent(agent, reputation_points))
    response.headers["Cache-Control"] = "public, max-age=60"
    response.headers["ETag"] = f'W/"agent:{agent.agent_id}:{int(agent.created_at.timestamp())}:{reputation_seed}"'
    return result


@router.post("/register", response_model=AgentRegisterResponse)
async def register_agent(
    payload: AgentRegisterRequest,
    request: Request,
    db: Session = Depends(get_db),
) -> AgentRegisterResponse:
    body_bytes = await request.body()
    body_hash = hash_body(body_bytes)
    request_id = request.headers.get("X-Request-ID") or str(uuid4())
    idempotency_key = request.headers.get("Idempotency-Key")

    agent_id = _generate_agent_id(db)
    api_key = generate_agent_api_key(agent_id)
    agent = Agent(
        agent_id=agent_id,
        name=payload.name,
        capabilities_json=json.dumps(payload.capabilities),
        wallet_address=payload.wallet_address,
        api_key_hash=hash_api_key(api_key),
        api_key_last4=api_key_last4(api_key),
    )
    # SQLAlchemy sessions auto-begin a transaction on first DB interaction (e.g. `_generate_agent_id`).
    # Using `with db.begin()` here can raise `InvalidRequestError: A transaction is already begun`.
    db.add(agent)
    db.flush()  # assign `agent.id` for the bootstrap reputation event

    ingest_reputation_event(
        db,
        ReputationEventCreateRequest(
            event_id=str(uuid4()),
            idempotency_key=f"rep:bootstrap:{agent.agent_id}",
            agent_id=agent.agent_id,
            delta_points=100,
            source="bootstrap",
            ref_type="agent",
            ref_id=agent.agent_id,
            note=None,
        ),
    )
    db.commit()
    db.refresh(agent)

    signature_status = getattr(request.state, "signature_status", "none")

    record_audit(
        db,
        actor_type="system",
        agent_id=agent.agent_id,
        method=request.method,
        path=request.url.path,
        idempotency_key=idempotency_key,
        body_hash=body_hash,
        signature_status=signature_status,
        request_id=request_id,
    )

    return AgentRegisterResponse(
        agent_id=agent.agent_id,
        api_key=api_key,
        created_at=agent.created_at,
    )


def _generate_agent_id(db: Session) -> str:
    for _ in range(5):
        candidate = f"ag_{secrets.token_hex(8)}"
        exists = db.query(Agent).filter(Agent.agent_id == candidate).first()
        if not exists:
            return candidate
    raise RuntimeError("Failed to generate unique agent id.")


def _public_agent(agent: Agent, reputation_points: int) -> PublicAgent:
    try:
        capabilities = json.loads(agent.capabilities_json or "[]")
    except json.JSONDecodeError:
        capabilities = []
    if not isinstance(capabilities, list):
        capabilities = []
    return PublicAgent(
        agent_id=agent.agent_id,
        name=agent.name,
        capabilities=capabilities,
        wallet_address=agent.wallet_address,
        created_at=agent.created_at,
        reputation_points=reputation_points,
    )
