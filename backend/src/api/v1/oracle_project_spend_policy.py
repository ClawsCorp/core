from __future__ import annotations

from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from src.api.v1.dependencies import require_oracle_hmac
from src.core.audit import record_audit
from src.core.database import get_db
from src.models.project import Project
from src.models.project_spend_policy import ProjectSpendPolicy
from src.schemas.project_spend_policy import (
    ProjectSpendPolicyPublic,
    ProjectSpendPolicyResponse,
    ProjectSpendPolicyUpsertRequest,
)

router = APIRouter(prefix="/api/v1/oracle/projects", tags=["oracle-projects"])


@router.post("/{project_id}/spend-policy", response_model=ProjectSpendPolicyResponse)
async def upsert_spend_policy(
    project_id: str,
    payload: ProjectSpendPolicyUpsertRequest,
    request: Request,
    _: str = Depends(require_oracle_hmac),
    db: Session = Depends(get_db),
) -> ProjectSpendPolicyResponse:
    project = db.query(Project).filter(Project.project_id == project_id).first()
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")

    row = db.query(ProjectSpendPolicy).filter(ProjectSpendPolicy.project_id == project.id).first()
    if row is None:
        row = ProjectSpendPolicy(project_id=project.id)
        db.add(row)

    row.per_bounty_cap_micro_usdc = payload.per_bounty_cap_micro_usdc
    row.per_day_cap_micro_usdc = payload.per_day_cap_micro_usdc
    row.per_month_cap_micro_usdc = payload.per_month_cap_micro_usdc

    request_id = request.headers.get("X-Request-Id") or request.headers.get("X-Request-ID") or str(uuid4())
    record_audit(
        db,
        actor_type="oracle",
        agent_id=None,
        method=request.method,
        path=request.url.path,
        idempotency_key=request.headers.get("Idempotency-Key"),
        body_hash=getattr(request.state, "body_hash", ""),
        signature_status=getattr(request.state, "signature_status", "invalid"),
        request_id=request_id,
        commit=False,
    )
    db.commit()
    db.refresh(row)

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

