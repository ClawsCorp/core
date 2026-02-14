from __future__ import annotations

import re
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from src.api.v1.dependencies import require_oracle_hmac
from src.core.audit import record_audit
from src.core.database import get_db
from src.models.project import Project
from src.models.project_revenue_reconciliation_report import ProjectRevenueReconciliationReport
from src.schemas.oracle_projects import (
    ProjectRevenueAddressSetData,
    ProjectRevenueAddressSetRequest,
    ProjectRevenueAddressSetResponse,
    ProjectRevenueReconciliationRunResponse,
)
from src.schemas.project import ProjectRevenueReconciliationReportPublic
from src.services.blockchain import BlockchainConfigError, BlockchainReadError, get_usdc_balance_micro_usdc
from src.services.project_revenue import get_project_revenue_balance_micro_usdc

router = APIRouter(prefix="/api/v1/oracle", tags=["oracle-project-revenue"])

_ADDRESS_RE = re.compile(r"^0x[a-f0-9]{40}$")


@router.post("/projects/{project_id}/revenue/address", response_model=ProjectRevenueAddressSetResponse)
async def set_project_revenue_address(
    project_id: str,
    payload: ProjectRevenueAddressSetRequest,
    request: Request,
    _: str = Depends(require_oracle_hmac),
    db: Session = Depends(get_db),
) -> ProjectRevenueAddressSetResponse:
    project = db.query(Project).filter(Project.project_id == project_id).first()
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")

    normalized = payload.revenue_address.strip().lower()
    idempotency_key = f"project_revenue_address:{project_id}:{normalized}"
    request_id = request.headers.get("X-Request-Id") or request.headers.get("X-Request-ID") or str(uuid4())
    body_hash = request.state.body_hash

    if not _ADDRESS_RE.fullmatch(normalized):
        _record_oracle_audit(request, db, body_hash, request_id, idempotency_key, commit=False)
        db.commit()
        return ProjectRevenueAddressSetResponse(
            success=False,
            data=ProjectRevenueAddressSetData(
                project_id=project_id,
                revenue_address=normalized,
                status="set",
                blocked_reason="invalid_address",
            ),
        )

    status = "unchanged" if project.revenue_address == normalized else "set"
    project.revenue_address = normalized
    _record_oracle_audit(request, db, body_hash, request_id, idempotency_key, commit=False)
    db.commit()
    return ProjectRevenueAddressSetResponse(
        success=True,
        data=ProjectRevenueAddressSetData(project_id=project_id, revenue_address=normalized, status=status),
    )


@router.post("/projects/{project_id}/revenue/reconciliation", response_model=ProjectRevenueReconciliationRunResponse)
async def reconcile_project_revenue(
    project_id: str,
    request: Request,
    _: str = Depends(require_oracle_hmac),
    db: Session = Depends(get_db),
) -> ProjectRevenueReconciliationRunResponse:
    project = db.query(Project).filter(Project.project_id == project_id).first()
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")

    request_id = request.headers.get("X-Request-Id") or request.headers.get("X-Request-ID") or str(uuid4())
    body_hash = request.state.body_hash
    idempotency_key = f"project_revenue_reconciliation:{project_id}:{request_id}"

    revenue_address = (project.revenue_address or "").strip().lower()
    if not revenue_address:
        report = ProjectRevenueReconciliationReport(
            project_id=project.id,
            revenue_address="",
            ledger_balance_micro_usdc=None,
            onchain_balance_micro_usdc=None,
            delta_micro_usdc=None,
            ready=False,
            blocked_reason="revenue_not_configured",
        )
        db.add(report)
        _record_oracle_audit(request, db, body_hash, request_id, idempotency_key, commit=False)
        db.commit()
        db.refresh(report)
        return ProjectRevenueReconciliationRunResponse(success=True, data=_recon_public(project_id, report))

    ledger_balance = get_project_revenue_balance_micro_usdc(db, project.id)

    try:
        onchain = get_usdc_balance_micro_usdc(revenue_address)
    except BlockchainConfigError:
        report = ProjectRevenueReconciliationReport(
            project_id=project.id,
            revenue_address=revenue_address,
            ledger_balance_micro_usdc=None,
            onchain_balance_micro_usdc=None,
            delta_micro_usdc=None,
            ready=False,
            blocked_reason="rpc_not_configured",
        )
    except BlockchainReadError:
        report = ProjectRevenueReconciliationReport(
            project_id=project.id,
            revenue_address=revenue_address,
            ledger_balance_micro_usdc=None,
            onchain_balance_micro_usdc=None,
            delta_micro_usdc=None,
            ready=False,
            blocked_reason="rpc_error",
        )
    else:
        delta = onchain.balance_micro_usdc - ledger_balance
        ready = delta == 0 and ledger_balance >= 0
        report = ProjectRevenueReconciliationReport(
            project_id=project.id,
            revenue_address=revenue_address,
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
    return ProjectRevenueReconciliationRunResponse(success=True, data=_recon_public(project_id, report))


def _record_oracle_audit(
    request: Request,
    db: Session,
    body_hash: str,
    request_id: str,
    idempotency_key: str,
    *,
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
        commit=commit,
    )


def _recon_public(
    project_id: str,
    report: ProjectRevenueReconciliationReport,
) -> ProjectRevenueReconciliationReportPublic:
    return ProjectRevenueReconciliationReportPublic(
        project_id=project_id,
        revenue_address=report.revenue_address,
        ledger_balance_micro_usdc=report.ledger_balance_micro_usdc,
        onchain_balance_micro_usdc=report.onchain_balance_micro_usdc,
        delta_micro_usdc=report.delta_micro_usdc,
        ready=report.ready,
        blocked_reason=report.blocked_reason,
        computed_at=report.computed_at,
    )

