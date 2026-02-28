# SPDX-License-Identifier: BSL-1.1

from __future__ import annotations

import json
from urllib.parse import urlparse

from sqlalchemy.orm import Session

from src.models.bounty import Bounty
from src.models.git_outbox import GitOutbox


_PLACEHOLDER_PR_HOSTS = {"example.invalid"}
_PLACEHOLDER_MERGE_SHAS = {"deadbeef"}
_TASK_TYPE_FRONTEND = "create_app_surface_commit"
_TASK_TYPE_BACKEND = "create_project_backend_artifact_commit"


def extract_git_pr_url(row: GitOutbox | None) -> str | None:
    if row is None or not row.result_json:
        return None
    try:
        parsed = json.loads(row.result_json)
    except ValueError:
        return None
    if not isinstance(parsed, dict):
        return None
    value = parsed.get("pr_url")
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def bounty_has_real_git_metadata(bounty: Bounty) -> bool:
    merge_sha = str(bounty.merge_sha or "").strip().lower()
    if merge_sha and merge_sha not in _PLACEHOLDER_MERGE_SHAS:
        return True
    pr_url = str(bounty.pr_url or "").strip()
    if pr_url and not _is_placeholder_pr_url(pr_url):
        return True
    return False


def bounty_needs_git_metadata_backfill(bounty: Bounty) -> bool:
    return not bounty_has_real_git_metadata(bounty)


def find_exact_git_outbox_for_bounty(db: Session, bounty: Bounty) -> GitOutbox | None:
    query = db.query(GitOutbox)
    if bounty.project_id is not None:
        query = query.filter(GitOutbox.project_id == bounty.project_id)
    query = query.order_by(GitOutbox.updated_at.desc(), GitOutbox.id.desc())

    if bounty.merge_sha:
        row = query.filter(GitOutbox.commit_sha == bounty.merge_sha).first()
        if row is not None:
            return row

    if bounty.pr_url:
        for candidate in query.limit(50).all():
            if extract_git_pr_url(candidate) == bounty.pr_url:
                return candidate

    return None


def infer_preferred_git_task_types(bounty: Bounty) -> list[str]:
    haystack = " ".join(
        part.strip().lower()
        for part in [bounty.title or "", bounty.description_md or ""]
        if isinstance(part, str) and part.strip()
    )
    preferred: list[str] = []
    if any(token in haystack for token in ("frontend", "surface", "ui", "landing")):
        preferred.append(_TASK_TYPE_FRONTEND)
    if any(token in haystack for token in ("backend", "api", "artifact", "endpoint")):
        preferred.append(_TASK_TYPE_BACKEND)
    for task_type in (_TASK_TYPE_FRONTEND, _TASK_TYPE_BACKEND):
        if task_type not in preferred:
            preferred.append(task_type)
    return preferred


def find_backfill_git_outbox_candidate(
    db: Session,
    bounty: Bounty,
    *,
    task_id: str | None = None,
    task_type: str | None = None,
) -> GitOutbox | None:
    query = db.query(GitOutbox).filter(GitOutbox.status == "succeeded")
    if bounty.project_id is not None:
        query = query.filter(GitOutbox.project_id == bounty.project_id)
    query = query.order_by(GitOutbox.updated_at.desc(), GitOutbox.id.desc())

    if task_id:
        candidate = query.filter(GitOutbox.task_id == task_id.strip()).first()
        if candidate is not None and _has_usable_git_metadata(candidate):
            return candidate
        return None

    if task_type:
        return _latest_candidate_for_task_type(query, task_type.strip())

    exact = find_exact_git_outbox_for_bounty(db, bounty)
    if exact is not None and _has_usable_git_metadata(exact):
        return exact

    for candidate_type in infer_preferred_git_task_types(bounty):
        candidate = _latest_candidate_for_task_type(query, candidate_type)
        if candidate is not None:
            return candidate
    return None


def apply_bounty_git_metadata_backfill(
    bounty: Bounty,
    candidate: GitOutbox,
    *,
    force: bool = False,
) -> bool:
    if not force and not bounty_needs_git_metadata_backfill(bounty):
        return False
    changed = False
    candidate_pr_url = extract_git_pr_url(candidate)
    if candidate_pr_url and bounty.pr_url != candidate_pr_url:
        bounty.pr_url = candidate_pr_url
        changed = True
    if candidate.commit_sha and bounty.merge_sha != candidate.commit_sha:
        bounty.merge_sha = candidate.commit_sha
        changed = True
    return changed


def _latest_candidate_for_task_type(query, task_type: str) -> GitOutbox | None:
    for candidate in query.filter(GitOutbox.task_type == task_type).limit(20).all():
        if _has_usable_git_metadata(candidate):
            return candidate
    return None


def _has_usable_git_metadata(candidate: GitOutbox) -> bool:
    return bool(str(candidate.commit_sha or "").strip() or extract_git_pr_url(candidate))


def _is_placeholder_pr_url(value: str) -> bool:
    parsed = urlparse(value.strip())
    host = (parsed.hostname or "").lower()
    return host in _PLACEHOLDER_PR_HOSTS
