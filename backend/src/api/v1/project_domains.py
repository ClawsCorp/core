from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.orm import Session

from src.core.database import get_db
from src.models.project import Project
from src.models.project_domain import ProjectDomain
from src.schemas.project_domain import ProjectDomainsData, ProjectDomainsListResponse, ProjectDomainPublic
from src.services.project_domains import verification_txt_name

router = APIRouter(prefix="/api/v1/projects", tags=["public-projects"])


@router.get("/{project_id}/domains", response_model=ProjectDomainsListResponse)
def list_project_domains(
    project_id: str,
    response: Response,
    db: Session = Depends(get_db),
) -> ProjectDomainsListResponse:
    project = db.query(Project).filter(Project.project_id == project_id).first()
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")

    rows = (
        db.query(ProjectDomain)
        .filter(ProjectDomain.project_id == project.id)
        .order_by(ProjectDomain.created_at.desc(), ProjectDomain.id.desc())
        .all()
    )
    items = [
        ProjectDomainPublic(
            domain_id=r.domain_id,
            project_id=project.project_id,
            domain=r.domain,
            status=r.status,
            dns_txt_name=verification_txt_name(r.domain),
            dns_txt_token=r.dns_txt_token,
            verified_at=r.verified_at,
            last_checked_at=r.last_checked_at,
            last_check_error=r.last_check_error,
            created_at=r.created_at,
            updated_at=r.updated_at,
        )
        for r in rows
    ]
    response.headers["Cache-Control"] = "public, max-age=30"
    return ProjectDomainsListResponse(success=True, data=ProjectDomainsData(items=items))

