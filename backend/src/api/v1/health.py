from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from core.config import get_settings
from core.database import engine

router = APIRouter()


@router.get("/health")
def health() -> dict[str, str]:
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

    return {
        "status": overall_status,
        "version": settings.app_version,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "db": db_status,
    }
