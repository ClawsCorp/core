from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class ProjectDomainPublic(BaseModel):
    domain_id: str
    project_id: str
    domain: str
    status: str
    dns_txt_name: str
    dns_txt_token: str
    verified_at: datetime | None
    last_checked_at: datetime | None
    last_check_error: str | None
    created_at: datetime
    updated_at: datetime


class ProjectDomainCreateRequest(BaseModel):
    domain: str = Field(..., min_length=3, max_length=255)


class ProjectDomainsData(BaseModel):
    items: list[ProjectDomainPublic]


class ProjectDomainsListResponse(BaseModel):
    success: bool
    data: ProjectDomainsData


class ProjectDomainCreateResponse(BaseModel):
    success: bool
    data: ProjectDomainPublic


class ProjectDomainVerifyResponse(BaseModel):
    success: bool
    data: ProjectDomainPublic
