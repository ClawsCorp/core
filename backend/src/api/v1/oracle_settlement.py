from __future__ import annotations

import re
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import func
from sqlalchemy.orm import Session

from src.api.v1.dependencies import require_oracle_hmac
from src.core.audit import record_audit
from src.core.database import get_db
from src.models.distribution_creation import DistributionCreation
from src.models.expense_event import ExpenseEvent
from src.models.reconciliation_report import ReconciliationReport
from src.models.revenue_event import RevenueEvent
from src.models.settlement import Settlement
from src.schemas.reconciliation import ReconciliationReportPublic
from src.schemas.settlement import (
    DistributionCreateResponse,
    PayoutTriggerRequest,
    PayoutTriggerResponse,
    SettlementPublic,
)
from src.services.blockchain import (
    BlockchainConfigError,
    BlockchainReadError,
    BlockchainTxError,
    read_distribution_state,
    read_usdc_balance_of_distributor,
    submit_create_distribution_tx,
)

router = APIRouter(prefix="/api/v1/oracle", tags=["oracle-settlement"])

_MONTH_RE = re.compile(r"^\d{6}$")
_MAX_STAKERS = 200
_MAX_AUTHORS = 50



@router.post("/settlement/{profit_month_id}", response_model=SettlementPublic)
def compute_settlement(
    profit_month_id: str,
    request: Request,
    _: str = Depends(require_oracle_hmac),
    db: Session = Depends(get_db),
) -> SettlementPublic:
    _validate_month(profit_month_id)
    revenue_sum = _month_revenue(db, profit_month_id)
    expense_sum = _month_expense(db, profit_month_id)
    profit_sum = revenue_sum - expense_sum

    settlement = Settlement(
        profit_month_id=profit_month_id,
        revenue_sum_micro_usdc=revenue_sum,
        expense_sum_micro_usdc=expense_sum,
        profit_sum_micro_usdc=profit_sum,
        profit_nonnegative=profit_sum >= 0,
    )
    db.add(settlement)
    db.commit()
    db.refresh(settlement)

    _record_oracle_audit(request, db)
    return _settlement_public(settlement)


@router.post("/reconciliation/{profit_month_id}", response_model=ReconciliationReportPublic)
def compute_reconciliation(
    profit_month_id: str,
    request: Request,
    _: str = Depends(require_oracle_hmac),
    db: Session = Depends(get_db),
) -> ReconciliationReportPublic:
    _validate_month(profit_month_id)
    settlement = _latest_settlement(db, profit_month_id)
    if settlement is None:
        _record_oracle_audit(request, db)
        raise HTTPException(status_code=409, detail="missing_settlement")

    try:
        balance = read_usdc_balance_of_distributor()
    except BlockchainConfigError:
        report = ReconciliationReport(
            profit_month_id=profit_month_id,
            revenue_sum_micro_usdc=settlement.revenue_sum_micro_usdc,
            expense_sum_micro_usdc=settlement.expense_sum_micro_usdc,
            profit_sum_micro_usdc=settlement.profit_sum_micro_usdc,
            distributor_balance_micro_usdc=None,
            delta_micro_usdc=None,
            ready=False,
            blocked_reason="rpc_not_configured",
            rpc_chain_id=None,
            rpc_url_name="base_sepolia",
        )
        db.add(report)
        db.commit()
        db.refresh(report)
        _record_oracle_audit(request, db)
        return _report_public(report)
    except BlockchainReadError:
        report = ReconciliationReport(
            profit_month_id=profit_month_id,
            revenue_sum_micro_usdc=settlement.revenue_sum_micro_usdc,
            expense_sum_micro_usdc=settlement.expense_sum_micro_usdc,
            profit_sum_micro_usdc=settlement.profit_sum_micro_usdc,
            distributor_balance_micro_usdc=None,
            delta_micro_usdc=None,
            ready=False,
            blocked_reason="rpc_error",
            rpc_chain_id=None,
            rpc_url_name="base_sepolia",
        )
        db.add(report)
        db.commit()
        db.refresh(report)
        _record_oracle_audit(request, db)
        return _report_public(report)

    delta = balance.balance_micro_usdc - settlement.profit_sum_micro_usdc
    if settlement.profit_sum_micro_usdc < 0:
        blocked_reason = "negative_profit"
        ready = False
    elif delta != 0:
        blocked_reason = "balance_mismatch"
        ready = False
    else:
        blocked_reason = None
        ready = True

    report = ReconciliationReport(
        profit_month_id=profit_month_id,
        revenue_sum_micro_usdc=settlement.revenue_sum_micro_usdc,
        expense_sum_micro_usdc=settlement.expense_sum_micro_usdc,
        profit_sum_micro_usdc=settlement.profit_sum_micro_usdc,
        distributor_balance_micro_usdc=balance.balance_micro_usdc,
        delta_micro_usdc=delta,
        ready=ready,
        blocked_reason=blocked_reason,
        rpc_chain_id=balance.rpc_chain_id,
        rpc_url_name=balance.rpc_url_name,
    )
    db.add(report)
    db.commit()
    db.refresh(report)

    _record_oracle_audit(request, db)
    return _report_public(report)


@router.post("/distributions/{profit_month_id}/create", response_model=DistributionCreateResponse)
def create_distribution(
    profit_month_id: str,
    request: Request,
    _: str = Depends(require_oracle_hmac),
    db: Session = Depends(get_db),
) -> DistributionCreateResponse:
    _validate_month(profit_month_id)

    report = _latest_reconciliation(db, profit_month_id)
    if report is None:
        _record_oracle_audit(request, db)
        return DistributionCreateResponse(
            success=False,
            data={
                "profit_month_id": profit_month_id,
                "status": "blocked",
                "tx_hash": None,
                "blocked_reason": "reconciliation_missing",
                "idempotency_key": _distribution_idempotency_key(profit_month_id, 0),
            },
        )
    if not report.ready:
        _record_oracle_audit(request, db)
        return DistributionCreateResponse(
            success=False,
            data={
                "profit_month_id": profit_month_id,
                "status": "blocked",
                "tx_hash": None,
                "blocked_reason": "not_ready",
                "idempotency_key": _distribution_idempotency_key(
                    profit_month_id, report.profit_sum_micro_usdc
                ),
            },
        )
    if report.profit_sum_micro_usdc <= 0:
        _record_oracle_audit(request, db)
        return DistributionCreateResponse(
            success=False,
            data={
                "profit_month_id": profit_month_id,
                "status": "blocked",
                "tx_hash": None,
                "blocked_reason": "profit_required",
                "idempotency_key": _distribution_idempotency_key(
                    profit_month_id, report.profit_sum_micro_usdc
                ),
            },
        )

    idempotency_key = _distribution_idempotency_key(profit_month_id, report.profit_sum_micro_usdc)
    profit_month_value = int(profit_month_id)

    existing_creation = (
        db.query(DistributionCreation)
        .filter(DistributionCreation.idempotency_key == idempotency_key)
        .order_by(DistributionCreation.id.desc())
        .first()
    )
    if existing_creation is not None:
        _record_oracle_audit(request, db, idempotency_key=idempotency_key, tx_hash=existing_creation.tx_hash)
        return DistributionCreateResponse(
            success=True,
            data={
                "profit_month_id": profit_month_id,
                "status": "submitted",
                "tx_hash": existing_creation.tx_hash,
                "blocked_reason": None,
                "idempotency_key": idempotency_key,
            },
        )

    try:
        distribution = read_distribution_state(profit_month_value)
    except BlockchainConfigError:
        _record_oracle_audit(request, db, idempotency_key=idempotency_key)
        return DistributionCreateResponse(
            success=False,
            data={
                "profit_month_id": profit_month_id,
                "status": "blocked",
                "tx_hash": None,
                "blocked_reason": "rpc_not_configured",
                "idempotency_key": idempotency_key,
            },
        )
    except BlockchainReadError:
        _record_oracle_audit(request, db, idempotency_key=idempotency_key)
        return DistributionCreateResponse(
            success=False,
            data={
                "profit_month_id": profit_month_id,
                "status": "blocked",
                "tx_hash": None,
                "blocked_reason": "tx_error",
                "idempotency_key": idempotency_key,
            },
        )

    if distribution.exists:
        _record_oracle_audit(request, db, idempotency_key=idempotency_key)
        return DistributionCreateResponse(
            success=True,
            data={
                "profit_month_id": profit_month_id,
                "status": "already_exists",
                "tx_hash": None,
                "blocked_reason": None,
                "idempotency_key": idempotency_key,
            },
        )

    try:
        tx_hash = submit_create_distribution_tx(
            profit_month_value=profit_month_value,
            total_profit_micro_usdc=report.profit_sum_micro_usdc,
        )
    except BlockchainConfigError as exc:
        blocked_reason = "signer_key_required" if "ORACLE_SIGNER_PRIVATE_KEY" in str(exc) else "rpc_not_configured"
        _record_oracle_audit(request, db, idempotency_key=idempotency_key)
        return DistributionCreateResponse(
            success=False,
            data={
                "profit_month_id": profit_month_id,
                "status": "blocked",
                "tx_hash": None,
                "blocked_reason": blocked_reason,
                "idempotency_key": idempotency_key,
            },
        )
    except BlockchainTxError as exc:
        _record_oracle_audit(
            request,
            db,
            idempotency_key=idempotency_key,
            error_hint=exc.error_hint,
        )
        return DistributionCreateResponse(
            success=False,
            data={
                "profit_month_id": profit_month_id,
                "status": "blocked",
                "tx_hash": None,
                "blocked_reason": "tx_error",
                "idempotency_key": idempotency_key,
            },
        )

    creation = DistributionCreation(
        profit_month_id=profit_month_id,
        profit_sum_micro_usdc=report.profit_sum_micro_usdc,
        idempotency_key=idempotency_key,
        tx_hash=tx_hash,
    )
    db.add(creation)
    db.commit()

    _record_oracle_audit(request, db, idempotency_key=idempotency_key, tx_hash=tx_hash)
    return DistributionCreateResponse(
        success=True,
        data={
            "profit_month_id": profit_month_id,
            "status": "submitted",
            "tx_hash": tx_hash,
            "blocked_reason": None,
            "idempotency_key": idempotency_key,
        },
    )


@router.post("/payouts/{profit_month_id}/trigger", response_model=PayoutTriggerResponse)
def trigger_payout(
    profit_month_id: str,
    payload: PayoutTriggerRequest,
    request: Request,
    _: str = Depends(require_oracle_hmac),
    db: Session = Depends(get_db),
) -> PayoutTriggerResponse:
    _validate_month(profit_month_id)

    report = _latest_reconciliation(db, profit_month_id)
    if report is None:
        _record_oracle_audit(request, db)
        return PayoutTriggerResponse(
            success=False,
            data={"profit_month_id": profit_month_id, "status": "blocked", "tx_hash": None, "blocked_reason": "missing_reconciliation"},
        )
    if not report.ready:
        _record_oracle_audit(request, db)
        return PayoutTriggerResponse(
            success=False,
            data={"profit_month_id": profit_month_id, "status": "blocked", "tx_hash": None, "blocked_reason": report.blocked_reason},
        )

    if payload.stakers_count > _MAX_STAKERS or payload.authors_count > _MAX_AUTHORS:
        _record_oracle_audit(request, db)
        return PayoutTriggerResponse(
            success=False,
            data={"profit_month_id": profit_month_id, "status": "blocked", "tx_hash": None, "blocked_reason": "recipient_caps_exceeded"},
        )

    # On-chain executeDistribution owner call is intentionally not wired here (secret signer key required).
    _record_oracle_audit(request, db)
    return PayoutTriggerResponse(
        success=False,
        data={
            "profit_month_id": profit_month_id,
            "status": "blocked",
            "tx_hash": None,
            "blocked_reason": "signer_key_required",
        },
    )


def _month_revenue(db: Session, profit_month_id: str) -> int:
    value = (
        db.query(func.sum(RevenueEvent.amount_micro_usdc))
        .filter(RevenueEvent.profit_month_id == profit_month_id)
        .scalar()
    )
    return int(value or 0)


def _month_expense(db: Session, profit_month_id: str) -> int:
    value = (
        db.query(func.sum(ExpenseEvent.amount_micro_usdc))
        .filter(ExpenseEvent.profit_month_id == profit_month_id)
        .scalar()
    )
    return int(value or 0)


def _latest_settlement(db: Session, profit_month_id: str) -> Settlement | None:
    return (
        db.query(Settlement)
        .filter(Settlement.profit_month_id == profit_month_id)
        .order_by(Settlement.computed_at.desc(), Settlement.id.desc())
        .first()
    )


def _latest_reconciliation(db: Session, profit_month_id: str) -> ReconciliationReport | None:
    return (
        db.query(ReconciliationReport)
        .filter(ReconciliationReport.profit_month_id == profit_month_id)
        .order_by(ReconciliationReport.computed_at.desc(), ReconciliationReport.id.desc())
        .first()
    )


def _distribution_idempotency_key(profit_month_id: str, profit_sum_micro_usdc: int) -> str:
    return f"create_distribution:{profit_month_id}:{profit_sum_micro_usdc}"


def _settlement_public(settlement: Settlement) -> SettlementPublic:
    return SettlementPublic(
        profit_month_id=settlement.profit_month_id,
        revenue_sum_micro_usdc=settlement.revenue_sum_micro_usdc,
        expense_sum_micro_usdc=settlement.expense_sum_micro_usdc,
        profit_sum_micro_usdc=settlement.profit_sum_micro_usdc,
        profit_nonnegative=settlement.profit_nonnegative,
        note=settlement.note,
        computed_at=settlement.computed_at,
    )


def _report_public(report: ReconciliationReport) -> ReconciliationReportPublic:
    return ReconciliationReportPublic(
        profit_month_id=report.profit_month_id,
        revenue_sum_micro_usdc=report.revenue_sum_micro_usdc,
        expense_sum_micro_usdc=report.expense_sum_micro_usdc,
        profit_sum_micro_usdc=report.profit_sum_micro_usdc,
        distributor_balance_micro_usdc=report.distributor_balance_micro_usdc,
        delta_micro_usdc=report.delta_micro_usdc,
        ready=report.ready,
        blocked_reason=report.blocked_reason,
        rpc_chain_id=report.rpc_chain_id,
        rpc_url_name=report.rpc_url_name,
        computed_at=report.computed_at,
    )


def _record_oracle_audit(
    request: Request,
    db: Session,
    *,
    idempotency_key: str | None = None,
    tx_hash: str | None = None,
    error_hint: str | None = None,
) -> None:
    body_hash = getattr(request.state, "body_hash", "")
    signature_status = getattr(request.state, "signature_status", "invalid")
    request_id = request.headers.get("X-Request-ID") or str(uuid4())
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
        tx_hash=tx_hash,
        error_hint=error_hint,
    )


def _validate_month(profit_month_id: str) -> None:
    if not _MONTH_RE.fullmatch(profit_month_id):
        raise HTTPException(status_code=400, detail="profit_month_id must use YYYYMM format")
    month = int(profit_month_id[4:6])
    if month < 1 or month > 12:
        raise HTTPException(status_code=400, detail="profit_month_id month must be 01..12")
