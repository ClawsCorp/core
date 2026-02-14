from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class TxOutboxEnqueueRequest(BaseModel):
    task_type: str = Field(..., min_length=1, max_length=64)
    payload: dict = Field(default_factory=dict)
    idempotency_key: str | None = Field(default=None, min_length=1, max_length=255)


class TxOutboxTask(BaseModel):
    task_id: str
    idempotency_key: str | None
    task_type: str
    payload: dict
    status: str
    attempts: int
    last_error_hint: str | None
    locked_at: datetime | None
    locked_by: str | None
    created_at: datetime
    updated_at: datetime


class TxOutboxTaskResponse(BaseModel):
    success: bool
    data: TxOutboxTask


class TxOutboxClaimRequest(BaseModel):
    worker_id: str = Field(..., min_length=1, max_length=64)


class TxOutboxClaimData(BaseModel):
    task: TxOutboxTask | None = None
    blocked_reason: str | None = None


class TxOutboxClaimResponse(BaseModel):
    success: bool
    data: TxOutboxClaimData


class TxOutboxCompleteRequest(BaseModel):
    status: str = Field(..., min_length=1, max_length=16)  # succeeded|failed
    error_hint: str | None = Field(default=None, max_length=2000)


class TxOutboxCompleteResponse(BaseModel):
    success: bool
    data: TxOutboxTask

