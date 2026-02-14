from __future__ import annotations

import hashlib
import re

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.orm import Session

from src.core.database import get_db
from src.models.project import Project
from src.models.project_settlement import ProjectSettlement
from src.schemas.project_settlement import (
    ProjectSettlementDetailData,
    ProjectSettlementDetailResponse,
    ProjectSettlementPublic,
)

router = APIRouter(prefix="/api/v1/projects", tags=["public-projects", "projects"])

_MONTH_RE = re.compile(r"^\d{6}$")


@router.get(
    "/{project_id}/settlement/{profit_month_id}",
    response_model=ProjectSettlementDetailResponse,
    summary="Get project settlement for month",
    description="Public read endpoint for a project's computed profit month summary (ledger-only).",
)
def get_project_settlement(
    project_id: str,
    profit_month_id: str,
    response: Response,
    db: Session = Depends(get_db),
) -> ProjectSettlementDetailResponse:
    _validate_month(profit_month_id)
    project = db.query(Project).filter(Project.project_id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    settlement = (
        db.query(ProjectSettlement)
        .filter(ProjectSettlement.project_id == project.id, ProjectSettlement.profit_month_id == profit_month_id)
        .order_by(ProjectSettlement.computed_at.desc(), ProjectSettlement.id.desc())
        .first()
    )

    result = ProjectSettlementDetailResponse(
        success=True,
        data=ProjectSettlementDetailData(
            settlement=_public(project.project_id, settlement) if settlement else None
        ),
    )

    settlement_ts = int(settlement.computed_at.timestamp()) if settlement else 0
    etag_seed = f"{project.project_id}:{profit_month_id}:{settlement_ts}".encode("utf-8", errors="replace")
    response.headers["Cache-Control"] = "public, max-age=30"
    response.headers["ETag"] = f'W/"project-settlement:{hashlib.sha256(etag_seed).hexdigest()[:16]}"'
    return result


def _public(project_id: str, settlement: ProjectSettlement) -> ProjectSettlementPublic:
    return ProjectSettlementPublic(
        project_id=project_id,
        profit_month_id=settlement.profit_month_id,
        revenue_sum_micro_usdc=int(settlement.revenue_sum_micro_usdc),
        expense_sum_micro_usdc=int(settlement.expense_sum_micro_usdc),
        profit_sum_micro_usdc=int(settlement.profit_sum_micro_usdc),
        profit_nonnegative=bool(settlement.profit_nonnegative),
        note=settlement.note,
        computed_at=settlement.computed_at,
    )


def _validate_month(profit_month_id: str) -> None:
    if not _MONTH_RE.fullmatch(profit_month_id):
        raise HTTPException(status_code=400, detail="profit_month_id must use YYYYMM format")
    month = int(profit_month_id[4:6])
    if month < 1 or month > 12:
        raise HTTPException(status_code=400, detail="profit_month_id month must be 01..12")

