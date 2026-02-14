from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from src.models.audit_log import AuditLog


@dataclass(frozen=True)
class RateLimitResult:
    allowed: bool
    attempts: int
    max_requests: int
    window_seconds: int


def _count_audits(
    db: Session,
    *,
    actor_type: str,
    agent_id: str,
    method: str,
    path_like: str,
    since: datetime,
) -> int:
    return int(
        (
            db.query(func.count(AuditLog.id))
            .filter(
                AuditLog.actor_type == actor_type,
                AuditLog.agent_id == agent_id,
                AuditLog.method == method,
                AuditLog.path.like(path_like),
                AuditLog.created_at >= since,
            )
            .scalar()
            or 0
        )
    )


def enforce_agent_rate_limit(
    db: Session,
    *,
    agent_id: str,
    method: str,
    path_like: str,
    max_requests: int,
    window_seconds: int,
    now: datetime | None = None,
) -> RateLimitResult:
    if max_requests <= 0 or window_seconds <= 0:
        return RateLimitResult(allowed=True, attempts=0, max_requests=max_requests, window_seconds=window_seconds)

    now = now or datetime.now(timezone.utc)
    since = now - timedelta(seconds=window_seconds)
    attempts = _count_audits(
        db,
        actor_type="agent",
        agent_id=agent_id,
        method=method,
        path_like=path_like,
        since=since,
    )

    allowed = attempts < max_requests
    if not allowed:
        raise HTTPException(
            status_code=429,
            detail=f"Rate limit exceeded: max {max_requests} requests per {window_seconds}s",
        )

    return RateLimitResult(allowed=True, attempts=attempts, max_requests=max_requests, window_seconds=window_seconds)

