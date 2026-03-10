from __future__ import annotations

import secrets
from datetime import datetime, timezone
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from src.api.v1.dependencies import require_agent_auth
from src.core.audit import record_audit
from src.core.database import get_db
from src.core.security import hash_body
from src.models.agent import Agent
from src.models.agent_social_identity import AgentSocialIdentity
from src.schemas.social_identities import (
    AgentSocialIdentityCreateRequest,
    AgentSocialIdentityListData,
    AgentSocialIdentityListResponse,
    AgentSocialIdentityPublic,
    AgentSocialIdentityResponse,
)

router = APIRouter(prefix="/api/v1", tags=["social-identities"])


@router.get("/agents/{agent_id}/social-identities", response_model=AgentSocialIdentityListResponse)
def list_agent_social_identities(
    agent_id: str,
    db: Session = Depends(get_db),
) -> AgentSocialIdentityListResponse:
    agent = _resolve_agent(db, agent_id)
    if agent is None:
        raise HTTPException(status_code=404, detail="Agent not found")
    rows = (
        db.query(AgentSocialIdentity)
        .filter(AgentSocialIdentity.agent_id == agent.id, AgentSocialIdentity.status == "active")
        .order_by(AgentSocialIdentity.platform.asc(), AgentSocialIdentity.handle.asc())
        .all()
    )
    return AgentSocialIdentityListResponse(
        success=True,
        data=AgentSocialIdentityListData(items=[_public_identity(agent.agent_id, row) for row in rows]),
    )


@router.post("/agent/social-identities", response_model=AgentSocialIdentityResponse)
async def create_agent_social_identity(
    payload: AgentSocialIdentityCreateRequest,
    request: Request,
    agent: Agent = Depends(require_agent_auth),
    db: Session = Depends(get_db),
) -> AgentSocialIdentityResponse:
    body_hash = hash_body(await request.body())
    request_id = request.headers.get("X-Request-ID") or str(uuid4())
    idempotency_key = request.headers.get("Idempotency-Key") or payload.idempotency_key

    platform = _normalize_platform(payload.platform)
    handle = _normalize_handle(payload.handle)

    existing = (
        db.query(AgentSocialIdentity)
        .filter(
            AgentSocialIdentity.platform == platform,
            AgentSocialIdentity.handle == handle,
            AgentSocialIdentity.status == "active",
        )
        .first()
    )
    if existing is not None:
        if int(existing.agent_id) != int(agent.id):
            raise HTTPException(status_code=409, detail="Social identity handle is already claimed.")
        _record_agent_audit(request, db, agent.agent_id, body_hash, request_id, idempotency_key)
        return AgentSocialIdentityResponse(success=True, data=_public_identity(agent.agent_id, existing))

    row = (
        db.query(AgentSocialIdentity)
        .filter(
            AgentSocialIdentity.agent_id == agent.id,
            AgentSocialIdentity.platform == platform,
            AgentSocialIdentity.handle == handle,
        )
        .order_by(AgentSocialIdentity.id.desc())
        .first()
    )
    if row is None:
        row = AgentSocialIdentity(
            identity_id=_generate_identity_id(db),
            agent_id=agent.id,
            platform=platform,
            handle=handle,
            status="active",
            revoked_at=None,
        )
        db.add(row)
    else:
        row.status = "active"
        row.revoked_at = None
        row.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(row)
    _record_agent_audit(request, db, agent.agent_id, body_hash, request_id, idempotency_key)
    return AgentSocialIdentityResponse(success=True, data=_public_identity(agent.agent_id, row))


@router.post("/agent/social-identities/{identity_id}/revoke", response_model=AgentSocialIdentityResponse)
async def revoke_agent_social_identity(
    identity_id: str,
    request: Request,
    agent: Agent = Depends(require_agent_auth),
    db: Session = Depends(get_db),
) -> AgentSocialIdentityResponse:
    body_hash = hash_body(await request.body())
    request_id = request.headers.get("X-Request-ID") or str(uuid4())
    idempotency_key = request.headers.get("Idempotency-Key")

    row = db.query(AgentSocialIdentity).filter(AgentSocialIdentity.identity_id == identity_id).first()
    if row is None:
        raise HTTPException(status_code=404, detail="Social identity not found")
    if int(row.agent_id) != int(agent.id):
        raise HTTPException(status_code=403, detail="Access denied.")

    if row.status != "revoked":
        row.status = "revoked"
        row.revoked_at = datetime.now(timezone.utc)
        row.updated_at = row.revoked_at
        db.commit()
        db.refresh(row)

    _record_agent_audit(request, db, agent.agent_id, body_hash, request_id, idempotency_key)
    return AgentSocialIdentityResponse(success=True, data=_public_identity(agent.agent_id, row))


def _resolve_agent(db: Session, identifier: str) -> Agent | None:
    if identifier.isdigit():
        return db.query(Agent).filter(Agent.id == int(identifier)).first()
    return db.query(Agent).filter(Agent.agent_id == identifier).first()


def _normalize_platform(value: str) -> str:
    platform = str(value or "").strip().lower()
    if not platform:
        raise HTTPException(status_code=400, detail="platform is required")
    return platform


def _normalize_handle(value: str) -> str:
    handle = str(value or "").strip().lower()
    if handle.startswith("@"):
        handle = handle[1:]
    if not handle:
        raise HTTPException(status_code=400, detail="handle is required")
    return handle


def _generate_identity_id(db: Session) -> str:
    for _ in range(5):
        candidate = f"sid_{secrets.token_hex(8)}"
        exists = db.query(AgentSocialIdentity).filter(AgentSocialIdentity.identity_id == candidate).first()
        if not exists:
            return candidate
    raise RuntimeError("Failed to generate unique social identity id")


def _public_identity(agent_id: str, row: AgentSocialIdentity) -> AgentSocialIdentityPublic:
    return AgentSocialIdentityPublic(
        identity_id=row.identity_id,
        agent_id=agent_id,
        platform=row.platform,
        handle=row.handle,
        status=row.status,
        created_at=row.created_at,
        updated_at=row.updated_at,
        revoked_at=row.revoked_at,
    )


def _record_agent_audit(
    request: Request,
    db: Session,
    agent_id: str,
    body_hash: str,
    request_id: str,
    idempotency_key: str | None,
) -> None:
    record_audit(
        db,
        actor_type="agent",
        agent_id=agent_id,
        method=request.method,
        path=request.url.path,
        idempotency_key=idempotency_key,
        body_hash=body_hash,
        signature_status="none",
        request_id=request_id,
    )
