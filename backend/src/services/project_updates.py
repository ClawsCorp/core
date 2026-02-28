from __future__ import annotations

import hashlib
import secrets

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from src.models.agent import Agent
from src.models.project import Project
from src.models.project_update import ProjectUpdate

MAX_PROJECT_UPDATE_IDEMPOTENCY_KEY_LEN = 255


def build_project_update_idempotency_key(*, prefix: str, source_idempotency_key: str) -> str:
    raw = f"{prefix}:{source_idempotency_key}"
    if len(raw) <= MAX_PROJECT_UPDATE_IDEMPOTENCY_KEY_LEN:
        return raw

    digest = hashlib.sha256(source_idempotency_key.encode("utf-8")).hexdigest()
    suffix = f"sha256:{digest}"
    max_prefix_len = MAX_PROJECT_UPDATE_IDEMPOTENCY_KEY_LEN - len(suffix) - 1
    safe_prefix = prefix[: max(0, max_prefix_len)]
    return f"{safe_prefix}:{suffix}"


def _generate_update_id(db: Session) -> str:
    for _ in range(5):
        candidate = f"pup_{secrets.token_hex(8)}"
        exists = db.query(ProjectUpdate.id).filter(ProjectUpdate.update_id == candidate).first()
        if exists is None:
            return candidate
    raise RuntimeError("Failed to generate unique project update id")


def create_project_update_row(
    db: Session,
    *,
    project: Project,
    agent: Agent | None,
    title: str,
    body_md: str | None,
    update_type: str,
    source_kind: str | None = None,
    source_ref: str | None = None,
    idempotency_key: str | None = None,
) -> tuple[ProjectUpdate, bool]:
    row = ProjectUpdate(
        update_id=_generate_update_id(db),
        idempotency_key=idempotency_key,
        project_id=project.id,
        author_agent_id=agent.id if agent is not None else None,
        update_type=str(update_type or "note").strip()[:32] or "note",
        title=str(title or "").strip()[:255] or "Project update",
        body_md=body_md.strip() if body_md and body_md.strip() else None,
        source_kind=source_kind.strip()[:32] if source_kind and source_kind.strip() else None,
        source_ref=source_ref.strip()[:128] if source_ref and source_ref.strip() else None,
    )
    try:
        with db.begin_nested():
            db.add(row)
            db.flush()
        return row, True
    except IntegrityError:
        if not idempotency_key:
            raise
        existing = db.query(ProjectUpdate).filter(ProjectUpdate.idempotency_key == idempotency_key).first()
        if existing is None:
            raise
        return existing, False


def project_update_public(project: Project, row: ProjectUpdate, author_agent_id: str | None) -> dict[str, object]:
    return {
        "update_id": row.update_id,
        "project_id": project.project_id,
        "author_agent_id": author_agent_id,
        "update_type": row.update_type,
        "title": row.title,
        "body_md": row.body_md,
        "source_kind": row.source_kind,
        "source_ref": row.source_ref,
        "created_at": row.created_at,
    }
