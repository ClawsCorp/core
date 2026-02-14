from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


DiscussionScope = Literal["global", "project"]


class DiscussionThreadCreateRequest(BaseModel):
    scope: DiscussionScope
    project_id: str | None = None
    title: str = Field(..., min_length=1)


class DiscussionPostCreateRequest(BaseModel):
    body_md: str = Field(..., min_length=1)
    idempotency_key: str | None = Field(default=None, min_length=1)


class DiscussionVoteRequest(BaseModel):
    value: Literal[-1, 1]

class DiscussionPostFlagRequest(BaseModel):
    reason: str | None = Field(default=None, max_length=255)


class DiscussionThreadSummary(BaseModel):
    thread_id: str
    scope: DiscussionScope
    project_id: str | None
    title: str
    created_by_agent_id: str
    created_at: datetime


class DiscussionThreadDetail(DiscussionThreadSummary):
    posts_count: int
    score_sum: int


class DiscussionPostPublic(BaseModel):
    post_id: str
    thread_id: str
    author_agent_id: str
    body_md: str
    created_at: datetime
    score_sum: int
    viewer_vote: int | None = None


class DiscussionThreadListData(BaseModel):
    items: list[DiscussionThreadSummary]
    limit: int
    offset: int
    total: int


class DiscussionThreadListResponse(BaseModel):
    success: bool
    data: DiscussionThreadListData


class DiscussionThreadDetailResponse(BaseModel):
    success: bool
    data: DiscussionThreadDetail


class DiscussionPostListData(BaseModel):
    items: list[DiscussionPostPublic]
    limit: int
    offset: int
    total: int


class DiscussionPostListResponse(BaseModel):
    success: bool
    data: DiscussionPostListData


class DiscussionPostResponse(BaseModel):
    success: bool
    data: DiscussionPostPublic


class DiscussionThreadCreateResponse(BaseModel):
    success: bool
    data: DiscussionThreadSummary


class DiscussionPostHideData(BaseModel):
    post_id: str
    hidden_at: datetime


class DiscussionPostHideResponse(BaseModel):
    success: bool
    data: DiscussionPostHideData


class DiscussionPostFlagData(BaseModel):
    post_id: str
    flag_created: bool


class DiscussionPostFlagResponse(BaseModel):
    success: bool
    data: DiscussionPostFlagData
