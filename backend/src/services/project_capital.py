from __future__ import annotations

from sqlalchemy import func
from sqlalchemy.orm import Session

from src.models.project import Project
from src.models.project_capital_event import ProjectCapitalEvent
from src.schemas.project_capital import ProjectCapitalSummary


def project_capital_summary(db: Session, project: Project) -> ProjectCapitalSummary:
    capital_sum, events_count, last_event_at = (
        db.query(
            func.coalesce(func.sum(ProjectCapitalEvent.delta_micro_usdc), 0),
            func.count(ProjectCapitalEvent.id),
            func.max(ProjectCapitalEvent.created_at),
        )
        .filter(ProjectCapitalEvent.project_id == project.id)
        .one()
    )
    return ProjectCapitalSummary(
        project_id=project.project_id,
        capital_sum_micro_usdc=int(capital_sum or 0),
        events_count=int(events_count or 0),
        last_event_at=last_event_at,
    )


def project_capital_leaderboard(db: Session, limit: int, offset: int) -> tuple[list[ProjectCapitalSummary], int]:
    base = (
        db.query(
            Project.id.label("project_pk"),
            Project.project_id.label("project_id"),
            func.coalesce(func.sum(ProjectCapitalEvent.delta_micro_usdc), 0).label("capital_sum_micro_usdc"),
            func.count(ProjectCapitalEvent.id).label("events_count"),
            func.max(ProjectCapitalEvent.created_at).label("last_event_at"),
        )
        .join(ProjectCapitalEvent, ProjectCapitalEvent.project_id == Project.id)
        .group_by(Project.id, Project.project_id)
    )
    total = base.count()
    rows = (
        base.order_by(
            func.coalesce(func.sum(ProjectCapitalEvent.delta_micro_usdc), 0).desc(),
            Project.project_id.asc(),
        )
        .offset(offset)
        .limit(limit)
        .all()
    )
    return [
        ProjectCapitalSummary(
            project_id=row.project_id,
            capital_sum_micro_usdc=int(row.capital_sum_micro_usdc or 0),
            events_count=int(row.events_count or 0),
            last_event_at=row.last_event_at,
        )
        for row in rows
    ], total
