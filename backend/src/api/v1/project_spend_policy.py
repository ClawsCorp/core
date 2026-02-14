from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from src.core.database import get_db
from src.models.project import Project
from src.models.project_spend_policy import ProjectSpendPolicy
from src.schemas.project_spend_policy import ProjectSpendPolicyResponse, ProjectSpendPolicyPublic

router = APIRouter(prefix="/api/v1/projects", tags=["public-projects"])


@router.get("/{project_id}/spend-policy", response_model=ProjectSpendPolicyResponse)
def get_spend_policy(project_id: str, db: Session = Depends(get_db)) -> ProjectSpendPolicyResponse:
    project = db.query(Project).filter(Project.project_id == project_id).first()
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")

    row = db.query(ProjectSpendPolicy).filter(ProjectSpendPolicy.project_id == project.id).first()
    if row is None:
        return ProjectSpendPolicyResponse(success=True, data=None)

    return ProjectSpendPolicyResponse(
        success=True,
        data=ProjectSpendPolicyPublic(
            project_id=project.project_id,
            per_bounty_cap_micro_usdc=row.per_bounty_cap_micro_usdc,
            per_day_cap_micro_usdc=row.per_day_cap_micro_usdc,
            per_month_cap_micro_usdc=row.per_month_cap_micro_usdc,
            created_at=row.created_at,
            updated_at=row.updated_at,
        ),
    )

