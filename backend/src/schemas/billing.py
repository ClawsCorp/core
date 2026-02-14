from __future__ import annotations

from pydantic import BaseModel


class BillingSyncData(BaseModel):
    billing_events_inserted: int
    revenue_events_inserted: int


class BillingSyncResponse(BaseModel):
    success: bool
    data: BillingSyncData

