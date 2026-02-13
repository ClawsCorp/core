from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel
from sqlalchemy.orm import Session

from src.core.config import get_settings
from src.core.database import get_db
from src.models.agent import Agent

router = APIRouter(prefix="/api/v1", tags=["public-system"])


class StatsData(BaseModel):
    app_version: str
    total_registered_agents: int
    server_time_utc: str
    project_capital_reconciliation_max_age_seconds: int


class StatsResponse(BaseModel):
    success: bool
    data: StatsData


@router.get(
    "/stats",
    response_model=StatsResponse,
    summary="Public platform stats",
    description="Portal-safe aggregate platform counters.",
)
def get_stats(response: Response, db: Session = Depends(get_db)) -> StatsResponse:
    settings = get_settings()
    total_agents = db.query(Agent).count()
    # Cache for 30s; round the displayed server time to the same bucket so ETag matches payload.
    now = datetime.now(timezone.utc)
    time_bucket_seconds = 30
    bucketed_timestamp = int(now.timestamp() // time_bucket_seconds) * time_bucket_seconds
    bucketed_time = datetime.fromtimestamp(bucketed_timestamp, tz=timezone.utc)
    result = StatsResponse(
        success=True,
        data=StatsData(
            app_version=settings.app_version,
            total_registered_agents=total_agents,
            server_time_utc=bucketed_time.isoformat(),
            project_capital_reconciliation_max_age_seconds=settings.project_capital_reconciliation_max_age_seconds,
        ),
    )
    etag_seed = (
        f"{result.data.app_version}:"
        f"{result.data.total_registered_agents}:"
        f"{bucketed_timestamp}:"
        f"{result.data.project_capital_reconciliation_max_age_seconds}"
    )
    response.headers["Cache-Control"] = "public, max-age=30"
    response.headers["ETag"] = f'W/"{etag_seed}"'
    return result
