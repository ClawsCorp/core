from __future__ import annotations

import re
import secrets
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import func
from sqlalchemy.orm import Session

from src.api.v1.dependencies import require_oracle_hmac
from src.core.audit import record_audit
from src.core.config import get_settings
from src.core.database import get_db
from src.core.db_utils import insert_or_get_by_unique
from src.models.project import Project
from src.models.project_capital_event import ProjectCapitalEvent
from src.models.project_capital_reconciliation_report import ProjectCapitalReconciliationReport
from src.schemas.oracle_projects import (
    ProjectCapitalReconciliationRunResponse,
    ProjectTreasurySetData,
    ProjectTreasurySetRequest,
    ProjectTreasurySetResponse,
)
from src.schemas.project import ProjectCapitalEventCreateRequest, ProjectCapitalEventDetailResponse, ProjectCapitalEventPublic
from src.schemas.project import ProjectCapitalReconciliationReportPublic
from src.services.blockchain import BlockchainConfigError, BlockchainReadError, get_usdc_balance_micro_usdc
from src.services.project_capital import get_latest_project_capital_reconciliation, is_reconciliation_fresh

router = APIRouter(prefix="/api/v1/oracle", tags=["oracle-project-capital"])

_MONTH_RE = re.compile(r"^\d{6}$")
_ADDRESS_RE = re.compile(r"^0x[a-f0-9]{40}$")


@router.post("/project-capital-events", response_model=ProjectCapitalEventDetailResponse)
async def create_project_capital_event(
    payload: ProjectCapitalEventCreateRequest,
    request: Request,
    _: str = Depends(require_oracle_hmac),
    db: Session = Depends(get_db),
) -> ProjectCapitalEventDetailResponse:
    if payload.profit_month_id is not None:
        _validate_month(payload.profit_month_id)
    if payload.delta_micro_usdc == 0:
        raise HTTPException(status_code=400, detail="delta_micro_usdc must be non-zero")

    project = db.query(Project).filter(Project.project_id == payload.project_id).first()
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")

    request_id = request.headers.get("X-Request-Id") or request.headers.get("X-Request-ID") or str(uuid4())
    body_hash = request.state.body_hash

    # Fail-closed: any project capital outflow requires a fresh strict-ready reconciliation
    # for the project's treasury anchor. This reduces the risk of drifting the ledger away
    # from on-chain reality before money-moving actions.
    if payload.delta_micro_usdc < 0:
        blocked_reason = _ensure_project_capital_outflow_reconciliation_gate(db, project.id)
        if blocked_reason is not None:
            compact_error_hint = (
                f"br={blocked_reason};"
                f"p={project.project_id};"
                f"idem={payload.idempotency_key};"
                f"d={payload.delta_micro_usdc};"
                f"src={payload.source}"
            )
            _record_oracle_audit(
                request,
                db,
                body_hash,
                request_id,
                payload.idempotency_key,
                error_hint=compact_error_hint,
                commit=False,
            )
            db.commit()
            return ProjectCapitalEventDetailResponse(
                success=False,
                data=None,
                blocked_reason=blocked_reason,
            )

    event = ProjectCapitalEvent(
        event_id=payload.event_id or _generate_event_id(db),
        idempotency_key=payload.idempotency_key,
        profit_month_id=payload.profit_month_id,
        project_id=project.id,
        delta_micro_usdc=payload.delta_micro_usdc,
        source=payload.source,
        evidence_tx_hash=payload.evidence_tx_hash,
        evidence_url=payload.evidence_url,
    )
    event, _ = insert_or_get_by_unique(
        db,
        instance=event,
        model=ProjectCapitalEvent,
        unique_filter={"idempotency_key": payload.idempotency_key},
    )
    _record_oracle_audit(request, db, body_hash, request_id, payload.idempotency_key, commit=False)
    db.commit()
    db.refresh(event)
    return ProjectCapitalEventDetailResponse(success=True, data=_public(project.project_id, event), blocked_reason=None)


@router.post("/projects/{project_id}/treasury", response_model=ProjectTreasurySetResponse)
async def set_project_treasury_address(
    project_id: str,
    payload: ProjectTreasurySetRequest,
    request: Request,
    _: str = Depends(require_oracle_hmac),
    db: Session = Depends(get_db),
) -> ProjectTreasurySetResponse:
    project = db.query(Project).filter(Project.project_id == project_id).first()
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")

    normalized = payload.treasury_address.strip().lower()
    idempotency_key = f"project_treasury:{project_id}:{normalized}"
    request_id = request.headers.get("X-Request-Id") or request.headers.get("X-Request-ID") or str(uuid4())
    body_hash = request.state.body_hash

    if not _ADDRESS_RE.fullmatch(normalized):
        _record_oracle_audit(request, db, body_hash, request_id, idempotency_key, commit=False)
        db.commit()
        return ProjectTreasurySetResponse(
            success=False,
            data=ProjectTreasurySetData(
                project_id=project_id,
                treasury_address=normalized,
                status="set",
                blocked_reason="invalid_address",
            ),
        )

    status = "unchanged" if project.treasury_address == normalized else "set"
    project.treasury_address = normalized
    _record_oracle_audit(request, db, body_hash, request_id, idempotency_key, commit=False)
    db.commit()
    return ProjectTreasurySetResponse(
        success=True,
        data=ProjectTreasurySetData(project_id=project_id, treasury_address=normalized, status=status),
    )


@router.post("/projects/{project_id}/capital/reconciliation", response_model=ProjectCapitalReconciliationRunResponse)
async def reconcile_project_capital(
    project_id: str,
    request: Request,
    _: str = Depends(require_oracle_hmac),
    db: Session = Depends(get_db),
) -> ProjectCapitalReconciliationRunResponse:
    project = db.query(Project).filter(Project.project_id == project_id).first()
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")

    request_id = request.headers.get("X-Request-Id") or request.headers.get("X-Request-ID") or str(uuid4())
    body_hash = request.state.body_hash
    idempotency_key = f"project_capital_reconciliation:{project_id}:{request_id}"

    if not project.treasury_address:
        report = ProjectCapitalReconciliationReport(
            project_id=project.id,
            treasury_address="",
            ledger_balance_micro_usdc=None,
            onchain_balance_micro_usdc=None,
            delta_micro_usdc=None,
            ready=False,
            blocked_reason="treasury_not_configured",
        )
        db.add(report)
        _record_oracle_audit(request, db, body_hash, request_id, idempotency_key, commit=False)
        db.commit()
        db.refresh(report)
        return ProjectCapitalReconciliationRunResponse(success=True, data=_recon_public(project_id, report))

    ledger_balance = int(
        db.query(func.coalesce(func.sum(ProjectCapitalEvent.delta_micro_usdc), 0))
        .filter(ProjectCapitalEvent.project_id == project.id)
        .scalar()
        or 0
    )

    try:
        onchain = get_usdc_balance_micro_usdc(project.treasury_address)
    except BlockchainConfigError:
        report = ProjectCapitalReconciliationReport(
            project_id=project.id,
            treasury_address=project.treasury_address,
            ledger_balance_micro_usdc=None,
            onchain_balance_micro_usdc=None,
            delta_micro_usdc=None,
            ready=False,
            blocked_reason="rpc_not_configured",
        )
    except BlockchainReadError:
        report = ProjectCapitalReconciliationReport(
            project_id=project.id,
            treasury_address=project.treasury_address,
            ledger_balance_micro_usdc=None,
            onchain_balance_micro_usdc=None,
            delta_micro_usdc=None,
            ready=False,
            blocked_reason="rpc_error",
        )
    else:
        delta = onchain.balance_micro_usdc - ledger_balance
        ready = delta == 0 and ledger_balance >= 0
        report = ProjectCapitalReconciliationReport(
            project_id=project.id,
            treasury_address=project.treasury_address,
            ledger_balance_micro_usdc=ledger_balance,
            onchain_balance_micro_usdc=onchain.balance_micro_usdc,
            delta_micro_usdc=delta,
            ready=ready,
            blocked_reason=None if ready else "balance_mismatch",
        )

    db.add(report)
    _record_oracle_audit(request, db, body_hash, request_id, idempotency_key, commit=False)
    db.commit()
    db.refresh(report)
    return ProjectCapitalReconciliationRunResponse(success=True, data=_recon_public(project_id, report))


def _validate_month(profit_month_id: str) -> None:
    if not _MONTH_RE.fullmatch(profit_month_id):
        raise HTTPException(status_code=400, detail="profit_month_id must use YYYYMM format")
    month = int(profit_month_id[4:6])
    if month < 1 or month > 12:
        raise HTTPException(status_code=400, detail="profit_month_id month must be 01..12")


def _generate_event_id(db: Session) -> str:
    for _ in range(5):
        candidate = f"pcap_{secrets.token_hex(8)}"
        if db.query(ProjectCapitalEvent).filter(ProjectCapitalEvent.event_id == candidate).first() is None:
            return candidate
    raise RuntimeError("Failed to generate unique event id.")


def _record_oracle_audit(
    request: Request,
    db: Session,
    body_hash: str,
    request_id: str,
    idempotency_key: str,
    error_hint: str | None = None,
    commit: bool = True,
) -> None:
    signature_status = getattr(request.state, "signature_status", "invalid")
    record_audit(
        db,
        actor_type="oracle",
        agent_id=None,
        method=request.method,
        path=request.url.path,
        idempotency_key=idempotency_key,
        body_hash=body_hash,
        signature_status=signature_status,
        request_id=request_id,
        error_hint=error_hint,
        commit=commit,
    )


def _ensure_project_capital_outflow_reconciliation_gate(db: Session, project_db_id: int) -> str | None:
    latest = get_latest_project_capital_reconciliation(db, project_db_id)
    if latest is None:
        return "project_capital_reconciliation_missing"
    if not latest.ready or latest.delta_micro_usdc != 0:
        return "project_capital_not_reconciled"

    settings = get_settings()
    if not is_reconciliation_fresh(latest, settings.project_capital_reconciliation_max_age_seconds):
        return "project_capital_reconciliation_stale"
    return None


def _public(project_id: str, event: ProjectCapitalEvent) -> ProjectCapitalEventPublic:
    return ProjectCapitalEventPublic(
        event_id=event.event_id,
        idempotency_key=event.idempotency_key,
        profit_month_id=event.profit_month_id,
        project_id=project_id,
        delta_micro_usdc=event.delta_micro_usdc,
        source=event.source,
        evidence_tx_hash=event.evidence_tx_hash,
        evidence_url=event.evidence_url,
        created_at=event.created_at,
    )


def _recon_public(project_id: str, report: ProjectCapitalReconciliationReport) -> ProjectCapitalReconciliationReportPublic:
    return ProjectCapitalReconciliationReportPublic(
        project_id=project_id,
        treasury_address=report.treasury_address,
        ledger_balance_micro_usdc=report.ledger_balance_micro_usdc,
        onchain_balance_micro_usdc=report.onchain_balance_micro_usdc,
        delta_micro_usdc=report.delta_micro_usdc,
        ready=report.ready,
        blocked_reason=report.blocked_reason,
        computed_at=report.computed_at,
    )
