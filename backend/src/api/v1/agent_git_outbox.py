# SPDX-License-Identifier: BSL-1.1

from __future__ import annotations

import hashlib
import json
import re
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session

from src.api.v1.dependencies import require_agent_auth
from src.core.audit import record_audit
from src.core.database import get_db
from src.core.git_outbox import enqueue_git_outbox_task
from src.core.security import hash_body
from src.models.agent import Agent
from src.models.bounty import Bounty
from src.models.git_outbox import GitOutbox
from src.models.project import Project
from src.models.project_member import ProjectMember
from src.schemas.git_outbox import (
    AgentGitOutboxCreateBackendArtifactRequest,
    AgentGitOutboxCreateSurfaceRequest,
    AgentGitOutboxListData,
    AgentGitOutboxListResponse,
    GitOutboxTask,
    GitOutboxTaskResponse,
)

router = APIRouter(prefix="/api/v1/agent/projects", tags=["agent-projects", "git-outbox"])

_SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_DEFAULT_DAO_PR_CHECKS = [
    "api-types",
    "backend",
    "contracts",
    "dependency-review",
    "frontend",
    "secrets-scan",
]


def _find_project_by_identifier(db: Session, identifier: str) -> Project | None:
    if identifier.isdigit():
        return db.query(Project).filter(Project.id == int(identifier)).first()
    return db.query(Project).filter(Project.project_id == identifier).first()


def _find_bounty_by_identifier(db: Session, identifier: str) -> Bounty | None:
    candidate = str(identifier or "").strip()
    if not candidate:
        return None
    if candidate.isdigit():
        row = db.query(Bounty).filter(Bounty.id == int(candidate)).first()
        if row is not None:
            return row
    return db.query(Bounty).filter(Bounty.bounty_id == candidate).first()


def _agent_can_access_project(db: Session, project: Project, agent: Agent) -> bool:
    if project.created_by_agent_id == agent.id or project.originator_agent_id == agent.id:
        return True
    row = (
        db.query(ProjectMember.id)
        .filter(ProjectMember.project_id == project.id, ProjectMember.agent_id == agent.id)
        .first()
    )
    return row is not None


def _validate_slug(value: str) -> str:
    slug = value.strip().lower()
    if not slug or len(slug) > 64 or _SLUG_RE.fullmatch(slug) is None:
        raise HTTPException(status_code=400, detail="invalid_slug")
    return slug


def _trim_or_none(value: str | None, *, max_length: int) -> str | None:
    if value is None:
        return None
    trimmed = value.strip()
    if not trimmed:
        return None
    return trimmed[:max_length]


def _safe_cta_href(value: str | None) -> str | None:
    if value is None:
        return None
    trimmed = value.strip()
    if not trimmed:
        return None
    if trimmed.startswith("/") or trimmed.startswith("http://") or trimmed.startswith("https://"):
        return trimmed[:512]
    raise HTTPException(status_code=400, detail="invalid_cta_href")


def _validated_bounty_link(db: Session, project: Project, bounty_id: str | None) -> str | None:
    candidate = str(bounty_id or "").strip()
    if not candidate:
        return None
    bounty = _find_bounty_by_identifier(db, candidate)
    if bounty is None:
        raise HTTPException(status_code=404, detail="Bounty not found")
    if bounty.project_id != project.id:
        raise HTTPException(status_code=400, detail="bounty_project_mismatch")
    return bounty.bounty_id


def _build_merge_policy(
    *,
    auto_merge: bool,
    required_checks: list[str],
    required_approvals: int,
    require_non_draft: bool,
) -> dict[str, object]:
    checks: list[str] = []
    for item in required_checks:
        candidate = str(item or "").strip()
        if not candidate:
            continue
        checks.append(candidate[:120])
    if auto_merge and not checks:
        checks = list(_DEFAULT_DAO_PR_CHECKS)
    return {
        "required_checks": checks,
        "required_approvals": max(0, int(required_approvals)),
        "require_non_draft": bool(require_non_draft),
    }


def _default_pr_title(project: Project, slug: str) -> str:
    return f"feat(surface): {project.name} - {slug}"


def _default_backend_pr_title(project: Project, slug: str) -> str:
    return f"feat(backend-artifact): {project.name} - {slug}"


def _default_pr_body(project: Project, slug: str, task_idempotency_key: str) -> str:
    return "\n".join(
        [
            "## Summary",
            f"- add generated app surface `{slug}` for project `{project.name}` (ID {project.project_id})",
            "- update product surface registry",
            "",
            "## Autonomous Task",
            f"- idempotency_key: `{task_idempotency_key}`",
            f"- project_id: `{project.project_id}`",
            "",
            "## Checklist",
            "- [ ] frontend lint/build passed",
            "- [ ] app surface opens on /apps/<slug>",
            "- [ ] copy/content reviewed",
        ]
    )


def _default_backend_pr_body(project: Project, slug: str, task_idempotency_key: str) -> str:
    return "\n".join(
        [
            "## Summary",
            f"- add generated backend artifact `{slug}` for project `{project.name}` (ID {project.project_id})",
            "- capture minimal API contract and operator checklist",
            "",
            "## Autonomous Task",
            f"- idempotency_key: `{task_idempotency_key}`",
            f"- project_id: `{project.project_id}`",
            "",
            "## Checklist",
            "- [ ] artifact file generated under backend/src/project_artifacts",
            "- [ ] endpoint list matches current project scope",
            "- [ ] follow-up tasks reference this artifact in discussions/bounties",
        ]
    )


def _to_task(row: GitOutbox) -> GitOutboxTask:
    result_obj: dict | None = None
    pr_url: str | None = None
    if row.result_json:
        try:
            parsed = json.loads(row.result_json)
            if isinstance(parsed, dict):
                result_obj = parsed
                parsed_pr_url = parsed.get("pr_url")
                if isinstance(parsed_pr_url, str) and parsed_pr_url.strip():
                    pr_url = parsed_pr_url.strip()
        except ValueError:
            result_obj = None
    return GitOutboxTask(
        task_id=row.task_id,
        idempotency_key=row.idempotency_key,
        project_num=row.project_id,
        requested_by_agent_num=row.requested_by_agent_id,
        task_type=row.task_type,
        payload=json.loads(row.payload_json or "{}"),
        result=result_obj,
        branch_name=row.branch_name,
        commit_sha=row.commit_sha,
        pr_url=pr_url,
        status=row.status,
        attempts=row.attempts,
        last_error_hint=row.last_error_hint,
        locked_at=row.locked_at,
        locked_by=row.locked_by,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


@router.post("/{project_id}/git-outbox/surface-commit", response_model=GitOutboxTaskResponse)
async def enqueue_project_surface_commit(
    project_id: str,
    payload: AgentGitOutboxCreateSurfaceRequest,
    request: Request,
    agent: Agent = Depends(require_agent_auth),
    db: Session = Depends(get_db),
) -> GitOutboxTaskResponse:
    body_hash = hash_body(await request.body())
    request_id = request.headers.get("X-Request-ID") or str(uuid4())

    project = _find_project_by_identifier(db, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    if not _agent_can_access_project(db, project, agent):
        raise HTTPException(status_code=403, detail="project_access_denied")

    slug = _validate_slug(payload.slug)
    bounty_id = _validated_bounty_link(db, project, payload.bounty_id)
    deterministic_seed = f"surface_commit:{project.project_id}:{agent.agent_id}:{slug}"
    deterministic_idempotency_key = f"surface_commit:{hashlib.sha256(deterministic_seed.encode('utf-8')).hexdigest()}"
    idempotency_key = request.headers.get("Idempotency-Key") or payload.idempotency_key or deterministic_idempotency_key

    worker_payload: dict[str, object] = {"slug": slug}
    if bounty_id:
        worker_payload["bounty_id"] = bounty_id
    if payload.branch_name:
        worker_payload["branch_name"] = payload.branch_name.strip()
    if payload.commit_message:
        worker_payload["commit_message"] = payload.commit_message.strip()
    surface_title = _trim_or_none(payload.surface_title, max_length=120)
    surface_tagline = _trim_or_none(payload.surface_tagline, max_length=180)
    surface_description = _trim_or_none(payload.surface_description, max_length=1200)
    cta_label = _trim_or_none(payload.cta_label, max_length=80)
    cta_href = _safe_cta_href(payload.cta_href)
    if surface_title:
        worker_payload["surface_title"] = surface_title
    if surface_tagline:
        worker_payload["surface_tagline"] = surface_tagline
    if surface_description:
        worker_payload["surface_description"] = surface_description
    if cta_label:
        worker_payload["cta_label"] = cta_label
    if cta_href:
        worker_payload["cta_href"] = cta_href
    worker_payload["open_pr"] = bool(payload.open_pr)
    if payload.auto_merge and not payload.open_pr:
        raise HTTPException(status_code=400, detail="auto_merge_requires_open_pr")
    worker_payload["auto_merge"] = bool(payload.auto_merge)
    worker_payload["merge_policy"] = _build_merge_policy(
        auto_merge=bool(payload.auto_merge),
        required_checks=payload.merge_policy_required_checks,
        required_approvals=payload.merge_policy_required_approvals,
        require_non_draft=payload.merge_policy_require_non_draft,
    )
    worker_payload["pr_title"] = (payload.pr_title.strip() if payload.pr_title else _default_pr_title(project, slug))
    worker_payload["pr_body"] = (
        payload.pr_body.strip() if payload.pr_body else _default_pr_body(project, slug, idempotency_key)
    )

    row = enqueue_git_outbox_task(
        db,
        task_type="create_app_surface_commit",
        payload=worker_payload,
        idempotency_key=idempotency_key,
        project_id=int(project.id),
        requested_by_agent_id=int(agent.id),
    )

    record_audit(
        db,
        actor_type="agent",
        agent_id=agent.agent_id,
        method=request.method,
        path=request.url.path,
        idempotency_key=idempotency_key,
        body_hash=body_hash,
        signature_status=getattr(request.state, "signature_status", "none"),
        request_id=request_id,
        commit=False,
    )
    db.commit()
    db.refresh(row)
    return GitOutboxTaskResponse(success=True, data=_to_task(row))


@router.post("/{project_id}/git-outbox/backend-artifact-commit", response_model=GitOutboxTaskResponse)
async def enqueue_project_backend_artifact_commit(
    project_id: str,
    payload: AgentGitOutboxCreateBackendArtifactRequest,
    request: Request,
    agent: Agent = Depends(require_agent_auth),
    db: Session = Depends(get_db),
) -> GitOutboxTaskResponse:
    body_hash = hash_body(await request.body())
    request_id = request.headers.get("X-Request-ID") or str(uuid4())

    project = _find_project_by_identifier(db, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    if not _agent_can_access_project(db, project, agent):
        raise HTTPException(status_code=403, detail="project_access_denied")

    slug = _validate_slug(payload.slug)
    bounty_id = _validated_bounty_link(db, project, payload.bounty_id)
    deterministic_seed = f"backend_artifact:{project.project_id}:{agent.agent_id}:{slug}"
    deterministic_idempotency_key = (
        f"backend_artifact:{hashlib.sha256(deterministic_seed.encode('utf-8')).hexdigest()}"
    )
    idempotency_key = request.headers.get("Idempotency-Key") or payload.idempotency_key or deterministic_idempotency_key

    endpoint_paths: list[str] = []
    for item in payload.endpoint_paths:
        candidate = item.strip()
        if not candidate:
            continue
        endpoint_paths.append(candidate[:200])

    worker_payload: dict[str, object] = {"slug": slug, "endpoint_paths": endpoint_paths}
    if bounty_id:
        worker_payload["bounty_id"] = bounty_id
    if payload.branch_name:
        worker_payload["branch_name"] = payload.branch_name.strip()
    if payload.commit_message:
        worker_payload["commit_message"] = payload.commit_message.strip()
    artifact_title = _trim_or_none(payload.artifact_title, max_length=160)
    artifact_summary = _trim_or_none(payload.artifact_summary, max_length=1200)
    if artifact_title:
        worker_payload["artifact_title"] = artifact_title
    if artifact_summary:
        worker_payload["artifact_summary"] = artifact_summary
    worker_payload["open_pr"] = bool(payload.open_pr)
    if payload.auto_merge and not payload.open_pr:
        raise HTTPException(status_code=400, detail="auto_merge_requires_open_pr")
    worker_payload["auto_merge"] = bool(payload.auto_merge)
    worker_payload["merge_policy"] = _build_merge_policy(
        auto_merge=bool(payload.auto_merge),
        required_checks=payload.merge_policy_required_checks,
        required_approvals=payload.merge_policy_required_approvals,
        require_non_draft=payload.merge_policy_require_non_draft,
    )
    worker_payload["pr_title"] = (
        payload.pr_title.strip() if payload.pr_title else _default_backend_pr_title(project, slug)
    )
    worker_payload["pr_body"] = (
        payload.pr_body.strip() if payload.pr_body else _default_backend_pr_body(project, slug, idempotency_key)
    )

    row = enqueue_git_outbox_task(
        db,
        task_type="create_project_backend_artifact_commit",
        payload=worker_payload,
        idempotency_key=idempotency_key,
        project_id=int(project.id),
        requested_by_agent_id=int(agent.id),
    )

    record_audit(
        db,
        actor_type="agent",
        agent_id=agent.agent_id,
        method=request.method,
        path=request.url.path,
        idempotency_key=idempotency_key,
        body_hash=body_hash,
        signature_status=getattr(request.state, "signature_status", "none"),
        request_id=request_id,
        commit=False,
    )
    db.commit()
    db.refresh(row)
    return GitOutboxTaskResponse(success=True, data=_to_task(row))


@router.get("/{project_id}/git-outbox", response_model=AgentGitOutboxListResponse)
def list_project_git_outbox(
    project_id: str,
    limit: int = Query(20, ge=1, le=100),
    agent: Agent = Depends(require_agent_auth),
    db: Session = Depends(get_db),
) -> AgentGitOutboxListResponse:
    project = _find_project_by_identifier(db, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    if not _agent_can_access_project(db, project, agent):
        raise HTTPException(status_code=403, detail="project_access_denied")

    query = db.query(GitOutbox).filter(GitOutbox.project_id == project.id)
    total = query.count()
    rows = query.order_by(GitOutbox.created_at.desc(), GitOutbox.id.desc()).limit(limit).all()
    return AgentGitOutboxListResponse(
        success=True,
        data=AgentGitOutboxListData(items=[_to_task(row) for row in rows], limit=limit, total=total),
    )
