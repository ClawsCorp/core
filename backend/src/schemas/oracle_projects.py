from __future__ import annotations

from pydantic import BaseModel, Field

from src.schemas.project import ProjectCapitalReconciliationReportPublic
from src.schemas.project import ProjectRevenueReconciliationReportPublic


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


class ProjectCapitalSyncData(BaseModel):
    transfers_seen: int
    capital_events_inserted: int
    projects_with_treasury_count: int


class ProjectCapitalSyncResponse(BaseModel):
    success: bool
    data: ProjectCapitalSyncData


class ProjectRevenueAddressSetRequest(BaseModel):
    revenue_address: str = Field(..., min_length=1)


class ProjectRevenueAddressSetData(BaseModel):
    project_id: str
    revenue_address: str | None
    status: str
    blocked_reason: str | None = None


class ProjectRevenueAddressSetResponse(BaseModel):
    success: bool
    data: ProjectRevenueAddressSetData


class ProjectRevenueReconciliationRunResponse(BaseModel):
    success: bool
    data: ProjectRevenueReconciliationReportPublic
