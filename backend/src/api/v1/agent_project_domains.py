from __future__ import annotations

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
from src.models.project_domain import ProjectDomain
from src.schemas.project_domain import (
    ProjectDomainCreateRequest,
    ProjectDomainCreateResponse,
    ProjectDomainPublic,
    ProjectDomainVerifyResponse,
)
from src.services.project_domains import normalize_domain, verification_txt_name, verify_domain

router = APIRouter(prefix="/api/v1/agent/projects", tags=["agent-projects"])


def _public(project: Project, row: ProjectDomain) -> ProjectDomainPublic:
    return ProjectDomainPublic(
        domain_id=row.domain_id,
        project_id=project.project_id,
        domain=row.domain,
        status=row.status,
        dns_txt_name=verification_txt_name(row.domain),
        dns_txt_token=row.dns_txt_token,
        verified_at=row.verified_at,
        last_checked_at=row.last_checked_at,
        last_check_error=row.last_check_error,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


@router.post("/{project_id}/domains", response_model=ProjectDomainCreateResponse)
async def create_domain(
    project_id: str,
    payload: ProjectDomainCreateRequest,
    request: Request,
    agent: Agent = Depends(require_agent_auth),
    db: Session = Depends(get_db),
) -> ProjectDomainCreateResponse:
    body_bytes = await request.body()
    body_hash = hash_body(body_bytes)
    request_id = request.headers.get("X-Request-ID") or str(uuid4())
    idempotency_key = request.headers.get("Idempotency-Key")

    project = db.query(Project).filter(Project.project_id == project_id).first()
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")

    try:
        domain = normalize_domain(payload.domain)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    row = ProjectDomain(project_id=project.id, domain=domain)
    db.add(row)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        existing = db.query(ProjectDomain).filter(ProjectDomain.domain == domain).first()
        if existing is None:
            raise
        row = existing
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

    return ProjectDomainCreateResponse(success=True, data=_public(project, row))


@router.post("/{project_id}/domains/{domain_id}/verify", response_model=ProjectDomainVerifyResponse)
async def verify_domain_endpoint(
    project_id: str,
    domain_id: str,
    request: Request,
    agent: Agent = Depends(require_agent_auth),
    db: Session = Depends(get_db),
) -> ProjectDomainVerifyResponse:
    body_bytes = await request.body()
    body_hash = hash_body(body_bytes)
    request_id = request.headers.get("X-Request-ID") or str(uuid4())
    idempotency_key = request.headers.get("Idempotency-Key") or f"verify_domain:{domain_id}"

    project = db.query(Project).filter(Project.project_id == project_id).first()
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")

    row = (
        db.query(ProjectDomain)
        .filter(ProjectDomain.domain_id == domain_id, ProjectDomain.project_id == project.id)
        .first()
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Domain not found")

    verify_domain(db, row=row)
    db.commit()
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

    return ProjectDomainVerifyResponse(success=True, data=_public(project, row))

