# SPDX-License-Identifier: BSL-1.1

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class GitOutboxEnqueueRequest(BaseModel):
    task_type: str = Field(..., min_length=1, max_length=64)
    payload: dict = Field(default_factory=dict)
    idempotency_key: str | None = Field(default=None, min_length=1, max_length=255)
    project_num: int | None = None
    requested_by_agent_num: int | None = None


class GitOutboxTask(BaseModel):
    task_id: str
    idempotency_key: str | None
    project_num: int | None = None
    requested_by_agent_num: int | None = None
    task_type: str
    payload: dict
    result: dict | None = None
    branch_name: str | None = None
    commit_sha: str | None = None
    pr_url: str | None = None
    status: str
    attempts: int
    last_error_hint: str | None
    locked_at: datetime | None
    locked_by: str | None
    created_at: datetime
    updated_at: datetime


class GitOutboxTaskResponse(BaseModel):
    success: bool
    data: GitOutboxTask


class GitOutboxClaimRequest(BaseModel):
    worker_id: str = Field(..., min_length=1, max_length=64)


class GitOutboxClaimData(BaseModel):
    task: GitOutboxTask | None = None
    blocked_reason: str | None = None


class GitOutboxClaimResponse(BaseModel):
    success: bool
    data: GitOutboxClaimData


class GitOutboxCompleteRequest(BaseModel):
    status: str = Field(..., min_length=1, max_length=16)  # succeeded|failed
    error_hint: str | None = Field(default=None, max_length=2000)
    result: dict | None = None
    branch_name: str | None = Field(default=None, max_length=128)
    commit_sha: str | None = Field(default=None, max_length=64)


class GitOutboxCompleteResponse(BaseModel):
    success: bool
    data: GitOutboxTask


class GitOutboxPendingData(BaseModel):
    items: list[GitOutboxTask]
    limit: int


class GitOutboxPendingResponse(BaseModel):
    success: bool
    data: GitOutboxPendingData


class GitOutboxUpdateRequest(BaseModel):
    result: dict | None = None
    branch_name: str | None = Field(default=None, max_length=128)
    commit_sha: str | None = Field(default=None, max_length=64)


class AgentGitOutboxCreateSurfaceRequest(BaseModel):
    slug: str = Field(..., min_length=1, max_length=64)
    branch_name: str | None = Field(default=None, min_length=1, max_length=128)
    commit_message: str | None = Field(default=None, min_length=1, max_length=200)
    surface_title: str | None = Field(default=None, min_length=1, max_length=120)
    surface_tagline: str | None = Field(default=None, min_length=1, max_length=180)
    surface_description: str | None = Field(default=None, min_length=1, max_length=1200)
    cta_label: str | None = Field(default=None, min_length=1, max_length=80)
    cta_href: str | None = Field(default=None, min_length=1, max_length=512)
    open_pr: bool = True
    pr_title: str | None = Field(default=None, min_length=1, max_length=200)
    pr_body: str | None = Field(default=None, min_length=1, max_length=5000)
    idempotency_key: str | None = Field(default=None, min_length=1, max_length=255)


class AgentGitOutboxListData(BaseModel):
    items: list[GitOutboxTask]
    limit: int
    total: int


class AgentGitOutboxListResponse(BaseModel):
    success: bool
    data: AgentGitOutboxListData
