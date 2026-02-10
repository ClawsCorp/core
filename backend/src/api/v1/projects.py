from __future__ import annotations

import secrets
from datetime import datetime, timezone
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from sqlalchemy.orm import Session

from src.api.v1.dependencies import require_oracle_hmac
from src.core.audit import record_audit
from src.core.database import get_db
from src.models.agent import Agent
from src.models.project import Project, ProjectStatus
from src.models.project_member import ProjectMember
from src.schemas.project import (
    ProjectCreateRequest,
    ProjectDetail,
    ProjectDetailResponse,
    ProjectListData,
    ProjectListResponse,
    ProjectMemberInfo,
    ProjectMemberRole,
    ProjectStatus as ProjectStatusSchema,
    ProjectStatusUpdateRequest,
    ProjectSummary,
)

router = APIRouter(prefix="/api/v1/projects", tags=["public-projects", "projects"])


@router.get(
    "",
    response_model=ProjectListResponse,
    summary="List projects",
    description="Public read endpoint for portal project list.",
)
def list_projects(
    status: ProjectStatusSchema | None = Query(None),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    response: Response | None = None,
) -> ProjectListResponse:
    query = db.query(Project)
    if status is not None:
        query = query.filter(Project.status == ProjectStatus(status))
    total = query.count()
    projects = query.order_by(Project.created_at.desc()).offset(offset).limit(limit).all()
    items = [_project_summary(project) for project in projects]
    result = ProjectListResponse(
        success=True,
        data=ProjectListData(items=items, limit=limit, offset=offset, total=total),
    )
    if response is not None:
        response.headers["Cache-Control"] = "public, max-age=60"
        response.headers["ETag"] = f'W/"projects:{status or "all"}:{offset}:{limit}:{total}"'
    return result


@router.get(
    "/{project_id}",
    response_model=ProjectDetailResponse,
    summary="Get project detail",
    description="Public read endpoint for a project and public member roster.",
)
def get_project(
    project_id: str,
    db: Session = Depends(get_db),
    response: Response | None = None,
) -> ProjectDetailResponse:
    project = db.query(Project).filter(Project.project_id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    result = ProjectDetailResponse(success=True, data=_project_detail(db, project))
    if response is not None:
        response.headers["Cache-Control"] = "public, max-age=60"
        response.headers["ETag"] = f'W/"project:{project.project_id}:{int(project.updated_at.timestamp())}"'
    return result


@router.post("", response_model=ProjectDetailResponse)
async def create_project(
    payload: ProjectCreateRequest,
    request: Request,
    _: str = Depends(require_oracle_hmac),
    db: Session = Depends(get_db),
) -> ProjectDetailResponse:
    request_id = request.headers.get("X-Request-ID") or str(uuid4())
    idempotency_key = request.headers.get("Idempotency-Key")
    body_hash = request.state.body_hash

    project_id = _generate_project_id(db)
    project = Project(
        project_id=project_id,
        name=payload.name,
        description_md=payload.description_md,
        status=ProjectStatus.draft,
        proposal_id=payload.proposal_id,
        treasury_wallet_address=payload.treasury_wallet_address,
        revenue_wallet_address=payload.revenue_wallet_address,
        monthly_budget_micro_usdc=payload.monthly_budget_micro_usdc,
    )
    db.add(project)
    db.commit()
    db.refresh(project)

    _record_oracle_audit(request, db, body_hash, request_id, idempotency_key)

    return ProjectDetailResponse(success=True, data=_project_detail(db, project))


@router.post("/{project_id}/approve", response_model=ProjectDetailResponse)
async def approve_project(
    project_id: str,
    request: Request,
    _: str = Depends(require_oracle_hmac),
    db: Session = Depends(get_db),
) -> ProjectDetailResponse:
    request_id = request.headers.get("X-Request-ID") or str(uuid4())
    idempotency_key = request.headers.get("Idempotency-Key")
    body_hash = request.state.body_hash

    project = db.query(Project).filter(Project.project_id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    if project.status == ProjectStatus.archived:
        raise HTTPException(status_code=400, detail="Archived projects are terminal.")

    project.status = ProjectStatus.active
    if project.approved_at is None:
        project.approved_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(project)

    _record_oracle_audit(request, db, body_hash, request_id, idempotency_key)

    return ProjectDetailResponse(success=True, data=_project_detail(db, project))


@router.post("/{project_id}/status", response_model=ProjectDetailResponse)
async def update_project_status(
    project_id: str,
    payload: ProjectStatusUpdateRequest,
    request: Request,
    _: str = Depends(require_oracle_hmac),
    db: Session = Depends(get_db),
) -> ProjectDetailResponse:
    request_id = request.headers.get("X-Request-ID") or str(uuid4())
    idempotency_key = request.headers.get("Idempotency-Key")
    body_hash = request.state.body_hash

    project = db.query(Project).filter(Project.project_id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    if project.status == ProjectStatus.archived and payload.status != ProjectStatus.archived:
        raise HTTPException(status_code=400, detail="Archived projects are terminal.")

    project.status = ProjectStatus(payload.status)
    if project.status == ProjectStatus.active and project.approved_at is None:
        project.approved_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(project)

    _record_oracle_audit(request, db, body_hash, request_id, idempotency_key)

    return ProjectDetailResponse(success=True, data=_project_detail(db, project))


def _record_oracle_audit(
    request: Request,
    db: Session,
    body_hash: str,
    request_id: str,
    idempotency_key: str | None,
) -> None:
    signature_status = getattr(request.state, "signature_status", "invalid")
    record_audit(
        db,
        actor_type="oracle",
        agent_id=None,
        method=request.method,
        path=request.url.path,
        idempotency_key=idempotency_key,
        body_hash=body_hash,
        signature_status=signature_status,
        request_id=request_id,
    )


def _generate_project_id(db: Session) -> str:
    for _ in range(5):
        candidate = f"proj_{secrets.token_hex(8)}"
        exists = db.query(Project).filter(Project.project_id == candidate).first()
        if not exists:
            return candidate
    raise RuntimeError("Failed to generate unique project id.")


def _project_summary(project: Project) -> ProjectSummary:
    return ProjectSummary(
        project_id=project.project_id,
        name=project.name,
        description_md=project.description_md,
        status=ProjectStatusSchema(project.status),
        proposal_id=project.proposal_id,
        treasury_wallet_address=project.treasury_wallet_address,
        revenue_wallet_address=project.revenue_wallet_address,
        monthly_budget_micro_usdc=project.monthly_budget_micro_usdc,
        created_at=project.created_at,
        updated_at=project.updated_at,
        approved_at=project.approved_at,
    )


def _project_detail(db: Session, project: Project) -> ProjectDetail:
    members = _load_project_members(db, project.id)
    return ProjectDetail(
        **_project_summary(project).model_dump(),
        members=members,
    )


def _load_project_members(db: Session, project_pk: int) -> list[ProjectMemberInfo]:
    rows = (
        db.query(Agent.agent_id, Agent.name, ProjectMember.role)
        .join(ProjectMember, ProjectMember.agent_id == Agent.id)
        .filter(ProjectMember.project_id == project_pk)
        .order_by(Agent.agent_id)
        .all()
    )
    return [
        ProjectMemberInfo(
            agent_id=row.agent_id,
            name=row.name,
            role=ProjectMemberRole(row.role),
        )
        for row in rows
    ]
