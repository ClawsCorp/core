from __future__ import annotations

from pydantic import BaseModel, Field

from src.schemas.project import ProjectCapitalReconciliationReportPublic


class ProjectTreasurySetRequest(BaseModel):
    treasury_address: str = Field(..., min_length=1)


class ProjectTreasurySetData(BaseModel):
    project_id: str
    treasury_address: str | None
    status: str
    blocked_reason: str | None = None


class ProjectTreasurySetResponse(BaseModel):
    success: bool
    data: ProjectTreasurySetData


class ProjectCapitalReconciliationRunResponse(BaseModel):
    success: bool
    data: ProjectCapitalReconciliationReportPublic
