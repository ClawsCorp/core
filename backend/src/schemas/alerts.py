from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class AlertItem(BaseModel):
    alert_type: str
    severity: str  # info|warning|critical
    message: str
    ref: str | None = None
    data: dict | None = None
    observed_at: datetime


class AlertsData(BaseModel):
    items: list[AlertItem]


class AlertsResponse(BaseModel):
    success: bool
    data: AlertsData

