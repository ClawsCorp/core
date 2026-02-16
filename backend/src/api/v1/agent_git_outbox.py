# SPDX-License-Identifier: BSL-1.1

from __future__ import annotations

import hashlib
import json
import re
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session

from src.api.v1.dependencies import require_agent_auth
from src.core.audit import record_audit
from src.core.database import get_db
from src.core.git_outbox import enqueue_git_outbox_task
from src.core.security import hash_body
from src.models.agent import Agent
from src.models.git_outbox import GitOutbox
from src.models.project import Project
from src.models.project_member import ProjectMember
from src.schemas.git_outbox import (
    AgentGitOutboxCreateSurfaceRequest,
    AgentGitOutboxListData,
    AgentGitOutboxListResponse,
    GitOutboxTask,
    GitOutboxTaskResponse,
)

router = APIRouter(prefix="/api/v1/agent/projects", tags=["agent-projects", "git-outbox"])

_SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


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


def _validate_slug(value: str) -> str:
    slug = value.strip().lower()
    if not slug or len(slug) > 64 or _SLUG_RE.fullmatch(slug) is None:
        raise HTTPException(status_code=400, detail="invalid_slug")
    return slug


def _to_task(row: GitOutbox) -> GitOutboxTask:
    result_obj: dict | None = None
    if row.result_json:
        try:
            parsed = json.loads(row.result_json)
            if isinstance(parsed, dict):
                result_obj = parsed
        except ValueError:
            result_obj = None
    return GitOutboxTask(
        task_id=row.task_id,
        idempotency_key=row.idempotency_key,
        project_num=row.project_id,
        requested_by_agent_num=row.requested_by_agent_id,
        task_type=row.task_type,
        payload=json.loads(row.payload_json or "{}"),
        result=result_obj,
        branch_name=row.branch_name,
        commit_sha=row.commit_sha,
        status=row.status,
        attempts=row.attempts,
        last_error_hint=row.last_error_hint,
        locked_at=row.locked_at,
        locked_by=row.locked_by,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


@router.post("/{project_id}/git-outbox/surface-commit", response_model=GitOutboxTaskResponse)
async def enqueue_project_surface_commit(
    project_id: str,
    payload: AgentGitOutboxCreateSurfaceRequest,
    request: Request,
    agent: Agent = Depends(require_agent_auth),
    db: Session = Depends(get_db),
) -> GitOutboxTaskResponse:
    body_hash = hash_body(await request.body())
    request_id = request.headers.get("X-Request-ID") or str(uuid4())

    project = _find_project_by_identifier(db, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    if not _agent_can_access_project(db, project, agent):
        raise HTTPException(status_code=403, detail="project_access_denied")

    slug = _validate_slug(payload.slug)
    deterministic_seed = f"surface_commit:{project.project_id}:{agent.agent_id}:{slug}"
    deterministic_idempotency_key = f"surface_commit:{hashlib.sha256(deterministic_seed.encode('utf-8')).hexdigest()}"
    idempotency_key = request.headers.get("Idempotency-Key") or payload.idempotency_key or deterministic_idempotency_key

    worker_payload: dict[str, str] = {"slug": slug}
    if payload.branch_name:
        worker_payload["branch_name"] = payload.branch_name.strip()
    if payload.commit_message:
        worker_payload["commit_message"] = payload.commit_message.strip()

    row = enqueue_git_outbox_task(
        db,
        task_type="create_app_surface_commit",
        payload=worker_payload,
        idempotency_key=idempotency_key,
        project_id=int(project.id),
        requested_by_agent_id=int(agent.id),
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
        commit=False,
    )
    db.commit()
    db.refresh(row)
    return GitOutboxTaskResponse(success=True, data=_to_task(row))


@router.get("/{project_id}/git-outbox", response_model=AgentGitOutboxListResponse)
def list_project_git_outbox(
    project_id: str,
    limit: int = Query(20, ge=1, le=100),
    agent: Agent = Depends(require_agent_auth),
    db: Session = Depends(get_db),
) -> AgentGitOutboxListResponse:
    project = _find_project_by_identifier(db, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    if not _agent_can_access_project(db, project, agent):
        raise HTTPException(status_code=403, detail="project_access_denied")

    query = db.query(GitOutbox).filter(GitOutbox.project_id == project.id)
    total = query.count()
    rows = query.order_by(GitOutbox.created_at.desc(), GitOutbox.id.desc()).limit(limit).all()
    return AgentGitOutboxListResponse(
        success=True,
        data=AgentGitOutboxListData(items=[_to_task(row) for row in rows], limit=limit, total=total),
    )
