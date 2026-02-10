from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Response
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from core.config import get_settings
from core.database import engine

router = APIRouter(prefix="/api/v1", tags=["public-system"])


@router.get(
    "/health",
    summary="Public health status",
    description="Portal-safe liveness status with no secrets.",
)
def health(response: Response) -> dict[str, str]:
    settings = get_settings()
    db_status = "not_configured"
    overall_status = "ok"

    if settings.database_url:
        if engine is None:
            db_status = "unhealthy"
            overall_status = "degraded"
        else:
            try:
                with engine.connect() as connection:
                    connection.execute(text("SELECT 1"))
                db_status = "ok"
            except SQLAlchemyError:
                db_status = "unhealthy"
                overall_status = "degraded"
    else:
        overall_status = "degraded"

    payload = {
        "status": overall_status,
        "version": settings.app_version,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "db": db_status,
    }
    response.headers["Cache-Control"] = "no-store"
    response.headers["ETag"] = f'W/"{payload["status"]}:{payload["version"]}:{payload["db"]}"'
    return payload
