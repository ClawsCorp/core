from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel
from sqlalchemy.orm import Session

from core.config import get_settings
from core.database import get_db
from models.agent import Agent

router = APIRouter(prefix="/api/v1", tags=["public-system"])


class StatsData(BaseModel):
    app_version: str
    total_registered_agents: int
    server_time_utc: str


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
    result = StatsResponse(
        success=True,
        data=StatsData(
            app_version=settings.app_version,
            total_registered_agents=total_agents,
            server_time_utc=datetime.now(timezone.utc).isoformat(),
        ),
    )
    etag_seed = f"{result.data.app_version}:{result.data.total_registered_agents}"
    response.headers["Cache-Control"] = "public, max-age=30"
    response.headers["ETag"] = f'W/"{etag_seed}"'
    return result
