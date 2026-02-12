from __future__ import annotations

from sqlalchemy.orm import Session

from src.models.audit_log import AuditLog


def record_audit(
    db: Session,
    *,
    actor_type: str,
    agent_id: str | None,
    method: str,
    path: str,
    idempotency_key: str | None,
    body_hash: str,
    signature_status: str,
    request_id: str,
    tx_hash: str | None = None,
    error_hint: str | None = None,
) -> AuditLog:
    audit_log = AuditLog(
        actor_type=actor_type,
        agent_id=agent_id,
        method=method,
        path=path,
        idempotency_key=idempotency_key,
        body_hash=body_hash,
        signature_status=signature_status,
        request_id=request_id,
        tx_hash=tx_hash,
        error_hint=error_hint,
    )
    db.add(audit_log)
    db.commit()
    db.refresh(audit_log)
    return audit_log
