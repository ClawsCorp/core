from __future__ import annotations

import secrets
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from src.api.v1.dependencies import require_agent_auth
from src.core.audit import record_audit
from src.core.database import get_db
from src.core.security import hash_body
from src.models.agent import Agent
from src.models.project import Project
from src.models.project_member import ProjectMember
from src.models.project_update import ProjectUpdate
from src.schemas.project import ProjectUpdateCreateRequest, ProjectUpdatePublic, ProjectUpdateResponse

router = APIRouter(prefix="/api/v1/agent/projects", tags=["agent-projects"])


def _find_project_by_identifier(db: Session, identifier: str) -> Project | None:
    if identifier.isdigit():
        return db.query(Project).filter(Project.id == int(identifier)).first()
    return db.query(Project).filter(Project.project_id == identifier).first()


def _agent_can_access_project(db: Session, project: Project, agent: Agent) -> bool:
    if project.created_by_agent_id == agent.id or project.originator_agent_id == agent.id:
        return True
    row = (
        db.query(ProjectMember.id)
        .filter(ProjectMember.project_id == project.id, ProjectMember.agent_id == agent.id)
        .first()
    )
    return row is not None


def _generate_update_id(db: Session) -> str:
    for _ in range(5):
        candidate = f"pup_{secrets.token_hex(8)}"
        exists = db.query(ProjectUpdate.id).filter(ProjectUpdate.update_id == candidate).first()
        if exists is None:
            return candidate
    raise RuntimeError("Failed to generate unique project update id")


def _to_public(project: Project, row: ProjectUpdate, agent: Agent | None = None) -> ProjectUpdatePublic:
    author_agent_id = agent.agent_id if agent is not None else None
    return ProjectUpdatePublic(
        update_id=row.update_id,
        project_id=project.project_id,
        author_agent_id=author_agent_id,
        update_type=row.update_type,
        title=row.title,
        body_md=row.body_md,
        source_kind=row.source_kind,
        source_ref=row.source_ref,
        created_at=row.created_at,
    )


@router.post("/{project_id}/updates", response_model=ProjectUpdateResponse)
async def create_project_update(
    project_id: str,
    payload: ProjectUpdateCreateRequest,
    request: Request,
    agent: Agent = Depends(require_agent_auth),
    db: Session = Depends(get_db),
) -> ProjectUpdateResponse:
    body_hash = hash_body(await request.body())
    request_id = request.headers.get("X-Request-ID") or str(uuid4())
    idempotency_key = request.headers.get("Idempotency-Key") or payload.idempotency_key

    project = _find_project_by_identifier(db, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    if not _agent_can_access_project(db, project, agent):
        raise HTTPException(status_code=403, detail="project_access_denied")

    row = ProjectUpdate(
        update_id=_generate_update_id(db),
        idempotency_key=idempotency_key,
        project_id=project.id,
        author_agent_id=agent.id,
        update_type=payload.update_type.strip()[:32],
        title=payload.title.strip()[:255],
        body_md=payload.body_md.strip() if payload.body_md and payload.body_md.strip() else None,
        source_kind=payload.source_kind.strip()[:32] if payload.source_kind and payload.source_kind.strip() else None,
        source_ref=payload.source_ref.strip()[:128] if payload.source_ref and payload.source_ref.strip() else None,
    )
    db.add(row)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        if not idempotency_key:
            raise
        existing = db.query(ProjectUpdate).filter(ProjectUpdate.idempotency_key == idempotency_key).first()
        if existing is None:
            raise
        record_audit(
            db,
            actor_type="agent",
            agent_id=agent.agent_id,
            method=request.method,
            path=request.url.path,
            idempotency_key=idempotency_key,
            body_hash=body_hash,
            signature_status=getattr(request.state, "signature_status", "none"),
            request_id=request_id,
        )
        author = db.query(Agent).filter(Agent.id == existing.author_agent_id).first() if existing.author_agent_id else None
        return ProjectUpdateResponse(success=True, data=_to_public(project, existing, author))

    db.refresh(row)
    record_audit(
        db,
        actor_type="agent",
        agent_id=agent.agent_id,
        method=request.method,
        path=request.url.path,
        idempotency_key=idempotency_key,
        body_hash=body_hash,
        signature_status=getattr(request.state, "signature_status", "none"),
        request_id=request_id,
    )
    author = db.query(Agent).filter(Agent.id == row.author_agent_id).first() if row.author_agent_id else None
    return ProjectUpdateResponse(success=True, data=_to_public(project, row, author))
