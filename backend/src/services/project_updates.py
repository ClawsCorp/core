from __future__ import annotations

import hashlib
import re
import secrets

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from src.models.agent import Agent
from src.models.project import Project
from src.models.project_update import ProjectUpdate

MAX_PROJECT_UPDATE_IDEMPOTENCY_KEY_LEN = 255
_TX_HASH_RE = re.compile(r"0x[a-fA-F0-9]{64}")


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
    ref_kind: str | None = None,
    ref_url: str | None = None,
    tx_hash: str | None = None,
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
        ref_kind=ref_kind.strip()[:32] if ref_kind and ref_kind.strip() else None,
        ref_url=ref_url.strip()[:255] if ref_url and ref_url.strip() else None,
        tx_hash=tx_hash.strip()[:66] if tx_hash and tx_hash.strip() else None,
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


def derive_project_update_ref(
    *,
    project_public_id: str,
    discussion_thread_id: str | None,
    source_kind: str | None,
    source_ref: str | None,
) -> tuple[str | None, str | None]:
    kind = (source_kind or "").strip()
    if kind in {"crypto_invoice", "crypto_invoice_paid", "billing_settlement"}:
        return "project_section", f"/projects/{project_public_id}#crypto-billing"
    if kind == "revenue_reconciliation_ready":
        return "project_section", f"/projects/{project_public_id}#revenue"
    if kind in {"capital_reconciliation_ready", "project_capital_event", "project_capital_sync"}:
        return "project_section", f"/projects/{project_public_id}#capital"
    if kind in {"revenue_outflow", "oracle_expense_event"}:
        return "project_section", f"/projects/{project_public_id}#project-accounting"
    if kind in {"revenue_bounty_paid", "bounty_paid"}:
        if source_ref:
            return "bounty", f"/bounties/{source_ref}"
        return "bounty_list", f"/bounties?project_id={project_public_id}"
    if kind in {"domain_create", "domain_verify", "project_domain"}:
        return "project_section", f"/projects/{project_public_id}#domains"
    if kind == "delivery_receipt":
        return "project_section", f"/projects/{project_public_id}#delivery-receipt"
    if kind in {"funding_round_open", "funding_round_close", "funding_round"}:
        return "project_section", f"/projects/{project_public_id}#fund-project"
    if discussion_thread_id:
        return "discussion_thread", f"/discussions/threads/{discussion_thread_id}"
    return "discussion_list", f"/discussions?scope=project&project_id={project_public_id}"


def extract_project_update_tx_hash(*, body_md: str | None, tx_hash: str | None) -> str | None:
    if tx_hash and tx_hash.strip():
        return tx_hash.strip()[:66]
    if not body_md:
        return None
    match = _TX_HASH_RE.search(body_md)
    if match is None:
        return None
    return match.group(0)


def populate_project_update_structured_refs(
    *,
    project_public_id: str,
    discussion_thread_id: str | None,
    row: ProjectUpdate,
) -> bool:
    changed = False
    if not row.ref_url:
        ref_kind, ref_url = derive_project_update_ref(
            project_public_id=project_public_id,
            discussion_thread_id=discussion_thread_id,
            source_kind=row.source_kind,
            source_ref=row.source_ref,
        )
        if not row.ref_kind and ref_kind:
            row.ref_kind = ref_kind
            changed = True
        if ref_url:
            row.ref_url = ref_url[:255]
            changed = True
    elif not row.ref_kind:
        ref_kind, _ = derive_project_update_ref(
            project_public_id=project_public_id,
            discussion_thread_id=discussion_thread_id,
            source_kind=row.source_kind,
            source_ref=row.source_ref,
        )
        if ref_kind:
            row.ref_kind = ref_kind
            changed = True

    derived_tx_hash = extract_project_update_tx_hash(body_md=row.body_md, tx_hash=row.tx_hash)
    if derived_tx_hash and row.tx_hash != derived_tx_hash:
        row.tx_hash = derived_tx_hash
        changed = True
    return changed


def project_update_public(project: Project, row: ProjectUpdate, author_agent_id: str | None) -> dict[str, object]:
    ref_kind = row.ref_kind
    ref_url = row.ref_url
    if not ref_url:
        ref_kind, ref_url = derive_project_update_ref(
            project_public_id=project.project_id,
            discussion_thread_id=project.discussion_thread_id,
            source_kind=row.source_kind,
            source_ref=row.source_ref,
        )
    tx_hash = extract_project_update_tx_hash(body_md=row.body_md, tx_hash=row.tx_hash)
    return {
        "update_id": row.update_id,
        "project_id": project.project_id,
        "author_agent_id": author_agent_id,
        "update_type": row.update_type,
        "title": row.title,
        "body_md": row.body_md,
        "source_kind": row.source_kind,
        "source_ref": row.source_ref,
        "ref_kind": ref_kind,
        "ref_url": ref_url,
        "tx_hash": tx_hash,
        "created_at": row.created_at,
    }
