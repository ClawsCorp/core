# SPDX-License-Identifier: BSL-1.1

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class ProjectCryptoInvoiceCreateRequest(BaseModel):
    amount_micro_usdc: int = Field(..., ge=1)
    payer_address: str | None = Field(default=None, min_length=1, max_length=42)
    description: str | None = Field(default=None, max_length=2000)
    chain_id: int = Field(default=84532, ge=1)
    idempotency_key: str | None = Field(default=None, min_length=1, max_length=255)


class ProjectCryptoInvoicePublic(BaseModel):
    invoice_id: str
    project_num: int
    project_id: str
    creator_agent_num: int | None
    chain_id: int
    token_address: str | None
    payment_address: str
    payer_address: str | None
    amount_micro_usdc: int
    description: str | None
    status: str
    observed_transfer_id: int | None
    paid_tx_hash: str | None
    paid_log_index: int | None
    paid_at: datetime | None
    created_at: datetime
    updated_at: datetime


class ProjectCryptoInvoiceResponse(BaseModel):
    success: bool
    data: ProjectCryptoInvoicePublic


class ProjectCryptoInvoiceListData(BaseModel):
    items: list[ProjectCryptoInvoicePublic]
    limit: int
    offset: int
    total: int


class ProjectCryptoInvoiceListResponse(BaseModel):
    success: bool
    data: ProjectCryptoInvoiceListData
