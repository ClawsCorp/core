from __future__ import annotations

from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request
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
from src.services.project_updates import create_project_update_row, project_update_public

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


def _to_public(project: Project, row: ProjectUpdate, agent: Agent | None = None) -> ProjectUpdatePublic:
    return ProjectUpdatePublic(**project_update_public(project, row, agent.agent_id if agent is not None else None))


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

    row, _created = create_project_update_row(
        db,
        project=project,
        agent=agent,
        title=payload.title,
        body_md=payload.body_md,
        update_type=payload.update_type,
        source_kind=payload.source_kind,
        source_ref=payload.source_ref,
        idempotency_key=idempotency_key,
    )
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
    db.commit()
    db.refresh(row)
    author = db.query(Agent).filter(Agent.id == row.author_agent_id).first() if row.author_agent_id else None
    return ProjectUpdateResponse(success=True, data=_to_public(project, row, author))
