from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import and_, func
from sqlalchemy.orm import Session

from src.api.v1.dependencies import require_oracle_hmac
from src.core.audit import record_audit
from src.core.config import get_settings
from src.core.database import get_db
from src.core.db_utils import insert_or_get_by_unique
from src.core.tx_outbox import enqueue_tx_outbox_task
from src.models.distribution_creation import DistributionCreation
from src.models.distribution_execution import DistributionExecution
from src.models.dividend_payout import DividendPayout
from src.models.expense_event import ExpenseEvent
from src.models.reconciliation_report import ReconciliationReport
from src.models.revenue_event import RevenueEvent
from src.models.settlement import Settlement
from src.models.tx_outbox import TxOutbox
from src.schemas.oracle import (
    PayoutConfirmRequest,
    PayoutConfirmResponse,
    PayoutSyncRequest,
    PayoutSyncResponse,
)
from src.schemas.reconciliation import ReconciliationReportPublic
from src.schemas.settlement import (
    DistributionCreateRecordRequest,
    DistributionCreateResponse,
    DistributionExecuteRecordRequest,
    DistributionExecuteRequest,
    DistributionExecuteResponse,
    PayoutTriggerRequest,
    PayoutTriggerResponse,
    SettlementPublic,
)
from src.services.blockchain import (
    BlockchainConfigError,
    BlockchainReadError,
    BlockchainTxError,
    read_distribution_state,
    read_transaction_receipt,
    read_usdc_balance_of_distributor,
    submit_create_distribution_tx,
    submit_execute_distribution_tx,
)

router = APIRouter(prefix="/api/v1/oracle", tags=["oracle-settlement"])

_MONTH_RE = re.compile(r"^\d{6}$")
_MAX_STAKERS = 200
_MAX_AUTHORS = 50
_TX_HASH_32_RE = re.compile(r"^0x[a-fA-F0-9]{64}$")


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
        idempotency_key = _distribution_idempotency_key(profit_month_id, 0)
        _record_oracle_audit(request, db, idempotency_key=idempotency_key)
        return DistributionCreateResponse(
            success=False,
            data={
                "profit_month_id": profit_month_id,
                "status": "blocked",
                "tx_hash": None,
                "blocked_reason": "reconciliation_missing",
                "idempotency_key": idempotency_key,
            },
        )
    if not report.ready:
        idempotency_key = _distribution_idempotency_key(
            profit_month_id, report.profit_sum_micro_usdc
        )
        _record_oracle_audit(request, db, idempotency_key=idempotency_key)
        return DistributionCreateResponse(
            success=False,
            data={
                "profit_month_id": profit_month_id,
                "status": "blocked",
                "tx_hash": None,
                "blocked_reason": "not_ready",
                "idempotency_key": idempotency_key,
            },
        )
    if report.profit_sum_micro_usdc <= 0:
        idempotency_key = _distribution_idempotency_key(
            profit_month_id, report.profit_sum_micro_usdc
        )
        _record_oracle_audit(request, db, idempotency_key=idempotency_key)
        return DistributionCreateResponse(
            success=False,
            data={
                "profit_month_id": profit_month_id,
                "status": "blocked",
                "tx_hash": None,
                "blocked_reason": "profit_required",
                "idempotency_key": idempotency_key,
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
                "task_id": None,
            },
        )

    settings = get_settings()
    if settings.tx_outbox_enabled:
        existing_task = (
            db.query(TxOutbox)
            .filter(TxOutbox.idempotency_key == idempotency_key)
            .order_by(TxOutbox.id.desc())
            .first()
        )
        if existing_task is not None:
            _record_oracle_audit(request, db, idempotency_key=idempotency_key)
            return DistributionCreateResponse(
                success=True,
                data={
                    "profit_month_id": profit_month_id,
                    "status": "queued",
                    "tx_hash": None,
                    "blocked_reason": None,
                    "idempotency_key": idempotency_key,
                    "task_id": existing_task.task_id,
                },
            )

        task = enqueue_tx_outbox_task(
            db,
            task_type="create_distribution",
            payload={
                "profit_month_id": profit_month_id,
                "profit_month_value": profit_month_value,
                "profit_sum_micro_usdc": int(report.profit_sum_micro_usdc),
                "idempotency_key": idempotency_key,
            },
            idempotency_key=idempotency_key,
        )
        _record_oracle_audit(request, db, idempotency_key=idempotency_key, commit=False)
        db.commit()
        return DistributionCreateResponse(
            success=True,
            data={
                "profit_month_id": profit_month_id,
                "status": "queued",
                "tx_hash": None,
                "blocked_reason": None,
                "idempotency_key": idempotency_key,
                "task_id": task.task_id,
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
    creation, _ = insert_or_get_by_unique(
        db,
        instance=creation,
        model=DistributionCreation,
        unique_filter={"idempotency_key": idempotency_key},
    )
    _record_oracle_audit(request, db, idempotency_key=idempotency_key, tx_hash=tx_hash, commit=False)
    db.commit()
    return DistributionCreateResponse(
        success=True,
        data={
            "profit_month_id": profit_month_id,
            "status": "submitted",
            "tx_hash": creation.tx_hash,
            "blocked_reason": None,
            "idempotency_key": idempotency_key,
            "task_id": None,
        },
    )


@router.post("/distributions/{profit_month_id}/execute", response_model=DistributionExecuteResponse)
def execute_distribution(
    profit_month_id: str,
    payload: DistributionExecuteRequest,
    request: Request,
    _: str = Depends(require_oracle_hmac),
    db: Session = Depends(get_db),
) -> DistributionExecuteResponse:
    _validate_month(profit_month_id)

    idempotency_key = _resolve_execute_idempotency_key(
        request=request,
        profit_month_id=profit_month_id,
        payload=payload,
    )

    existing_execution = (
        db.query(DistributionExecution)
        .filter(DistributionExecution.idempotency_key == idempotency_key)
        .order_by(DistributionExecution.id.desc())
        .first()
    )
    if existing_execution is not None:
        success = existing_execution.status in {"submitted", "already_distributed"}
        _record_oracle_audit(
            request,
            db,
            idempotency_key=idempotency_key,
            tx_hash=existing_execution.tx_hash,
        )
        return DistributionExecuteResponse(
            success=success,
            data={
                "profit_month_id": existing_execution.profit_month_id,
                "status": existing_execution.status,
                "tx_hash": existing_execution.tx_hash,
                "blocked_reason": existing_execution.blocked_reason,
                "idempotency_key": idempotency_key,
                "task_id": None,
            },
        )

    settlement = _latest_settlement(db, profit_month_id)
    if settlement is None:
        return _record_blocked_execution(
            request,
            db,
            profit_month_id=profit_month_id,
            idempotency_key=idempotency_key,
            blocked_reason="missing_settlement",
        )

    report = _latest_reconciliation(db, profit_month_id)
    if report is None:
        return _record_blocked_execution(
            request,
            db,
            profit_month_id=profit_month_id,
            idempotency_key=idempotency_key,
            blocked_reason="reconciliation_missing",
        )
    if not report.ready or report.delta_micro_usdc != 0:
        return _record_blocked_execution(
            request,
            db,
            profit_month_id=profit_month_id,
            idempotency_key=idempotency_key,
            blocked_reason="not_ready",
        )

    try:
        distribution = read_distribution_state(int(profit_month_id))
    except BlockchainConfigError:
        return _record_blocked_execution(
            request,
            db,
            profit_month_id=profit_month_id,
            idempotency_key=idempotency_key,
            blocked_reason="rpc_not_configured",
        )
    except BlockchainReadError:
        return _record_blocked_execution(
            request,
            db,
            profit_month_id=profit_month_id,
            idempotency_key=idempotency_key,
            blocked_reason="tx_error",
        )

    if not distribution.exists:
        return _record_blocked_execution(
            request,
            db,
            profit_month_id=profit_month_id,
            idempotency_key=idempotency_key,
            blocked_reason="distribution_missing",
        )

    if distribution.distributed:
        execution = DistributionExecution(
            profit_month_id=profit_month_id,
            idempotency_key=idempotency_key,
            status="already_distributed",
            tx_hash=None,
            blocked_reason=None,
        )
        execution, _ = insert_or_get_by_unique(
            db,
            instance=execution,
            model=DistributionExecution,
            unique_filter={"idempotency_key": idempotency_key},
        )
        _record_oracle_audit(request, db, idempotency_key=idempotency_key, commit=False)
        db.commit()
        return DistributionExecuteResponse(
            success=True,
            data={
                "profit_month_id": execution.profit_month_id,
                "status": execution.status,
                "tx_hash": execution.tx_hash,
                "blocked_reason": execution.blocked_reason,
                "idempotency_key": idempotency_key,
                "task_id": None,
            },
        )

    if distribution.total_profit_micro_usdc != settlement.profit_sum_micro_usdc:
        return _record_blocked_execution(
            request,
            db,
            profit_month_id=profit_month_id,
            idempotency_key=idempotency_key,
            blocked_reason="distribution_total_mismatch",
        )

    validation_error = _validate_execute_distribution_payload(payload)
    if validation_error is not None:
        return _record_blocked_execution(
            request,
            db,
            profit_month_id=profit_month_id,
            idempotency_key=idempotency_key,
            blocked_reason=validation_error,
        )

    settings = get_settings()
    if settings.tx_outbox_enabled:
        existing_task = (
            db.query(TxOutbox)
            .filter(TxOutbox.idempotency_key == idempotency_key)
            .order_by(TxOutbox.id.desc())
            .first()
        )
        if existing_task is not None:
            _record_oracle_audit(request, db, idempotency_key=idempotency_key)
            return DistributionExecuteResponse(
                success=True,
                data={
                    "profit_month_id": profit_month_id,
                    "status": "queued",
                    "tx_hash": None,
                    "blocked_reason": None,
                    "idempotency_key": idempotency_key,
                    "task_id": existing_task.task_id,
                },
            )

        task = enqueue_tx_outbox_task(
            db,
            task_type="execute_distribution",
            payload={
                "profit_month_id": profit_month_id,
                "profit_month_value": int(profit_month_id),
                "idempotency_key": idempotency_key,
                "stakers": payload.stakers,
                "staker_shares": payload.staker_shares,
                "authors": payload.authors,
                "author_shares": payload.author_shares,
                "total_profit_micro_usdc": int(settlement.profit_sum_micro_usdc),
                "stakers_count": len(payload.stakers),
                "authors_count": len(payload.authors),
            },
            idempotency_key=idempotency_key,
        )
        _record_oracle_audit(request, db, idempotency_key=idempotency_key, commit=False)
        db.commit()
        return DistributionExecuteResponse(
            success=True,
            data={
                "profit_month_id": profit_month_id,
                "status": "queued",
                "tx_hash": None,
                "blocked_reason": None,
                "idempotency_key": idempotency_key,
                "task_id": task.task_id,
            },
        )

    try:
        tx_hash = submit_execute_distribution_tx(
            profit_month_value=int(profit_month_id),
            stakers=payload.stakers,
            staker_shares=payload.staker_shares,
            authors=payload.authors,
            author_shares=payload.author_shares,
        )
    except BlockchainConfigError as exc:
        blocked_reason = "signer_key_required" if "ORACLE_SIGNER_PRIVATE_KEY" in str(exc) else "rpc_not_configured"
        return _record_blocked_execution(
            request,
            db,
            profit_month_id=profit_month_id,
            idempotency_key=idempotency_key,
            blocked_reason=blocked_reason,
        )
    except BlockchainTxError as exc:
        return _record_blocked_execution(
            request,
            db,
            profit_month_id=profit_month_id,
            idempotency_key=idempotency_key,
            blocked_reason="tx_error",
            error_hint=exc.error_hint,
        )

    execution = DistributionExecution(
        profit_month_id=profit_month_id,
        idempotency_key=idempotency_key,
        status="submitted",
        tx_hash=tx_hash,
        blocked_reason=None,
    )
    execution, _ = insert_or_get_by_unique(
        db,
        instance=execution,
        model=DistributionExecution,
        unique_filter={"idempotency_key": idempotency_key},
    )
    _upsert_dividend_payout(
        db,
        profit_month_id=profit_month_id,
        idempotency_key=idempotency_key,
        tx_hash=tx_hash,
        total_profit_micro_usdc=settlement.profit_sum_micro_usdc,
        stakers_count=len(payload.stakers),
        authors_count=len(payload.authors),
    )
    _record_oracle_audit(request, db, idempotency_key=idempotency_key, tx_hash=tx_hash, commit=False)
    db.commit()
    return DistributionExecuteResponse(
        success=execution.status in {"submitted", "already_distributed"},
        data={
            "profit_month_id": execution.profit_month_id,
            "status": execution.status,
            "tx_hash": execution.tx_hash,
            "blocked_reason": execution.blocked_reason,
            "idempotency_key": idempotency_key,
            "task_id": None,
        },
    )


@router.post("/distributions/{profit_month_id}/create/record", response_model=DistributionCreateResponse)
def record_create_distribution_tx(
    profit_month_id: str,
    payload: DistributionCreateRecordRequest,
    request: Request,
    _: str = Depends(require_oracle_hmac),
    db: Session = Depends(get_db),
) -> DistributionCreateResponse:
    _validate_month(profit_month_id)

    existing = (
        db.query(DistributionCreation)
        .filter(DistributionCreation.idempotency_key == payload.idempotency_key)
        .order_by(DistributionCreation.id.desc())
        .first()
    )
    if existing is not None:
        _record_oracle_audit(request, db, idempotency_key=payload.idempotency_key, tx_hash=existing.tx_hash)
        return DistributionCreateResponse(
            success=True,
            data={
                "profit_month_id": existing.profit_month_id,
                "status": "submitted",
                "tx_hash": existing.tx_hash,
                "blocked_reason": None,
                "idempotency_key": existing.idempotency_key,
                "task_id": None,
            },
        )

    creation = DistributionCreation(
        profit_month_id=profit_month_id,
        profit_sum_micro_usdc=int(payload.profit_sum_micro_usdc),
        idempotency_key=payload.idempotency_key,
        tx_hash=payload.tx_hash,
    )
    creation, _ = insert_or_get_by_unique(
        db,
        instance=creation,
        model=DistributionCreation,
        unique_filter={"idempotency_key": payload.idempotency_key},
    )
    _record_oracle_audit(request, db, idempotency_key=payload.idempotency_key, tx_hash=payload.tx_hash, commit=False)
    db.commit()
    return DistributionCreateResponse(
        success=True,
        data={
            "profit_month_id": creation.profit_month_id,
            "status": "submitted",
            "tx_hash": creation.tx_hash,
            "blocked_reason": None,
            "idempotency_key": creation.idempotency_key,
            "task_id": None,
        },
    )


@router.post("/distributions/{profit_month_id}/execute/record", response_model=DistributionExecuteResponse)
def record_execute_distribution_tx(
    profit_month_id: str,
    payload: DistributionExecuteRecordRequest,
    request: Request,
    _: str = Depends(require_oracle_hmac),
    db: Session = Depends(get_db),
) -> DistributionExecuteResponse:
    _validate_month(profit_month_id)

    existing = (
        db.query(DistributionExecution)
        .filter(DistributionExecution.idempotency_key == payload.idempotency_key)
        .order_by(DistributionExecution.id.desc())
        .first()
    )
    if existing is not None:
        _record_oracle_audit(request, db, idempotency_key=payload.idempotency_key, tx_hash=existing.tx_hash)
        return DistributionExecuteResponse(
            success=True,
            data={
                "profit_month_id": existing.profit_month_id,
                "status": existing.status,
                "tx_hash": existing.tx_hash,
                "blocked_reason": existing.blocked_reason,
                "idempotency_key": existing.idempotency_key,
                "task_id": None,
            },
        )

    execution = DistributionExecution(
        profit_month_id=profit_month_id,
        idempotency_key=payload.idempotency_key,
        status="submitted",
        tx_hash=payload.tx_hash,
        blocked_reason=None,
    )
    execution, _ = insert_or_get_by_unique(
        db,
        instance=execution,
        model=DistributionExecution,
        unique_filter={"idempotency_key": payload.idempotency_key},
    )
    _upsert_dividend_payout(
        db,
        profit_month_id=profit_month_id,
        idempotency_key=payload.idempotency_key,
        tx_hash=payload.tx_hash,
        total_profit_micro_usdc=int(payload.total_profit_micro_usdc),
        stakers_count=int(payload.stakers_count),
        authors_count=int(payload.authors_count),
    )
    _record_oracle_audit(request, db, idempotency_key=payload.idempotency_key, tx_hash=payload.tx_hash, commit=False)
    db.commit()
    return DistributionExecuteResponse(
        success=True,
        data={
            "profit_month_id": execution.profit_month_id,
            "status": execution.status,
            "tx_hash": execution.tx_hash,
            "blocked_reason": execution.blocked_reason,
            "idempotency_key": execution.idempotency_key,
            "task_id": None,
        },
    )


@router.post("/payouts/{profit_month_id}/sync", response_model=PayoutSyncResponse)
def sync_payout_metadata(
    profit_month_id: str,
    payload: PayoutSyncRequest,
    request: Request,
    _: str = Depends(require_oracle_hmac),
    db: Session = Depends(get_db),
) -> PayoutSyncResponse:
    _validate_month(profit_month_id)

    tx_hash = payload.tx_hash
    if tx_hash is not None:
        _validate_tx_hash_32(tx_hash)
        tx_hash = tx_hash_lower(tx_hash)
    else:
        tx_hash = _discover_execution_tx_hash(db, profit_month_id)
        if tx_hash is None:
            return _blocked_sync_response(
                request,
                db,
                profit_month_id=profit_month_id,
                blocked_reason="tx_hash_required",
                tx_hash=None,
            )
        _validate_tx_hash_32(tx_hash)
        tx_hash = tx_hash_lower(tx_hash)

    idempotency_key = _sync_payout_idempotency_key(profit_month_id, tx_hash)

    existing = (
        db.query(DividendPayout)
        .filter(
            (DividendPayout.idempotency_key == idempotency_key)
            | and_(DividendPayout.profit_month_id == profit_month_id, DividendPayout.tx_hash == tx_hash)
        )
        .order_by(DividendPayout.id.desc())
        .first()
    )
    if existing is not None:
        _record_oracle_audit(request, db, idempotency_key=idempotency_key, tx_hash=existing.tx_hash)
        return PayoutSyncResponse(
            success=True,
            data={
                "profit_month_id": profit_month_id,
                "status": "already_synced",
                "tx_hash": existing.tx_hash,
                "blocked_reason": None,
                "idempotency_key": existing.idempotency_key or idempotency_key,
                "executed_at": existing.payout_executed_at,
            },
        )

    report = _latest_reconciliation(db, profit_month_id)
    if report is None:
        return _blocked_sync_response(
            request,
            db,
            profit_month_id=profit_month_id,
            blocked_reason="reconciliation_missing",
            idempotency_key=idempotency_key,
            tx_hash=tx_hash,
        )
    if not report.ready or report.delta_micro_usdc != 0:
        return _blocked_sync_response(
            request,
            db,
            profit_month_id=profit_month_id,
            blocked_reason="not_ready",
            idempotency_key=idempotency_key,
            tx_hash=tx_hash,
        )

    try:
        distribution = read_distribution_state(int(profit_month_id))
    except BlockchainConfigError:
        return _blocked_sync_response(
            request,
            db,
            profit_month_id=profit_month_id,
            blocked_reason="rpc_not_configured",
            idempotency_key=idempotency_key,
            tx_hash=tx_hash,
        )
    except BlockchainReadError:
        return _blocked_sync_response(
            request,
            db,
            profit_month_id=profit_month_id,
            blocked_reason="rpc_error",
            idempotency_key=idempotency_key,
            tx_hash=tx_hash,
        )

    if not distribution.exists:
        return _blocked_sync_response(
            request,
            db,
            profit_month_id=profit_month_id,
            blocked_reason="distribution_missing",
            idempotency_key=idempotency_key,
            tx_hash=tx_hash,
        )

    if not distribution.distributed:
        return _blocked_sync_response(
            request,
            db,
            profit_month_id=profit_month_id,
            blocked_reason="not_distributed",
            idempotency_key=idempotency_key,
            tx_hash=tx_hash,
        )

    payout = DividendPayout(
        profit_month_id=profit_month_id,
        idempotency_key=idempotency_key,
        status="synced",
        tx_hash=tx_hash,
        stakers_count=0,
        authors_count=0,
        total_stakers_micro_usdc=0,
        total_treasury_micro_usdc=0,
        total_authors_micro_usdc=0,
        total_founder_micro_usdc=0,
        total_payout_micro_usdc=0,
        payout_executed_at=func.now(),
    )
    payout, _ = insert_or_get_by_unique(
        db,
        instance=payout,
        model=DividendPayout,
        unique_filter={"idempotency_key": idempotency_key},
    )
    _record_oracle_audit(request, db, idempotency_key=idempotency_key, tx_hash=tx_hash, commit=False)
    db.commit()
    db.refresh(payout)
    return PayoutSyncResponse(
        success=True,
        data={
            "profit_month_id": profit_month_id,
            "status": "synced",
            "tx_hash": payout.tx_hash,
            "blocked_reason": None,
            "idempotency_key": payout.idempotency_key or idempotency_key,
            "executed_at": payout.payout_executed_at,
        },
    )


@router.post("/payouts/{profit_month_id}/confirm", response_model=PayoutConfirmResponse)
def confirm_payout_status(
    profit_month_id: str,
    payload: PayoutConfirmRequest,
    request: Request,
    _: str = Depends(require_oracle_hmac),
    db: Session = Depends(get_db),
) -> PayoutConfirmResponse:
    _validate_month(profit_month_id)

    tx_hash = payload.tx_hash
    if tx_hash is None:
        tx_hash = _discover_payout_tx_hash(db, profit_month_id)
    if tx_hash is None:
        return _blocked_confirm_response(
            request,
            db,
            profit_month_id=profit_month_id,
            blocked_reason="tx_error",
            idempotency_key=f"confirm_payout:{profit_month_id}:missing",
            tx_hash=None,
            status="pending",
        )

    _validate_tx_hash_32(tx_hash)
    tx_hash = tx_hash_lower(tx_hash)
    idempotency_key = f"confirm_payout:{profit_month_id}:{tx_hash}"

    payout = _latest_payout_for_tx(db, profit_month_id, tx_hash)
    if payout is None:
        return _blocked_confirm_response(
            request,
            db,
            profit_month_id=profit_month_id,
            blocked_reason="tx_error",
            idempotency_key=idempotency_key,
            tx_hash=tx_hash,
            status="pending",
        )

    try:
        receipt = read_transaction_receipt(tx_hash)
    except BlockchainConfigError:
        return _blocked_confirm_response(
            request,
            db,
            profit_month_id=profit_month_id,
            blocked_reason="rpc_not_configured",
            idempotency_key=idempotency_key,
            tx_hash=tx_hash,
            status=payout.status,
            error_hint="rpc_not_configured",
        )
    except BlockchainReadError:
        return _blocked_confirm_response(
            request,
            db,
            profit_month_id=profit_month_id,
            blocked_reason="rpc_error",
            idempotency_key=idempotency_key,
            tx_hash=tx_hash,
            status=payout.status,
            error_hint="rpc_error",
        )

    if not receipt.found:
        if payout.status == "synced":
            payout.status = "pending"
            db.commit()
            db.refresh(payout)
        _record_oracle_audit(request, db, idempotency_key=idempotency_key, tx_hash=tx_hash)
        return PayoutConfirmResponse(
            success=True,
            data={
                "profit_month_id": profit_month_id,
                "status": payout.status,
                "tx_hash": tx_hash,
                "blocked_reason": None,
                "idempotency_key": idempotency_key,
                "confirmed_at": payout.confirmed_at,
                "failed_at": payout.failed_at,
                "block_number": payout.block_number,
            },
        )

    if payout.status in {"confirmed", "failed"}:
        _record_oracle_audit(request, db, idempotency_key=idempotency_key, tx_hash=tx_hash)
        return PayoutConfirmResponse(
            success=True,
            data={
                "profit_month_id": profit_month_id,
                "status": payout.status,
                "tx_hash": tx_hash,
                "blocked_reason": None,
                "idempotency_key": idempotency_key,
                "confirmed_at": payout.confirmed_at,
                "failed_at": payout.failed_at,
                "block_number": payout.block_number,
            },
        )

    now = datetime.now(timezone.utc)
    payout.block_number = receipt.block_number
    if receipt.status == 1:
        payout.status = "confirmed"
        payout.confirmed_at = payout.confirmed_at or now
        payout.failed_at = None
    else:
        payout.status = "failed"
        payout.failed_at = payout.failed_at or now
        payout.confirmed_at = None

    db.commit()
    db.refresh(payout)
    _record_oracle_audit(request, db, idempotency_key=idempotency_key, tx_hash=tx_hash)
    return PayoutConfirmResponse(
        success=True,
        data={
            "profit_month_id": profit_month_id,
            "status": payout.status,
            "tx_hash": tx_hash,
            "blocked_reason": None,
            "idempotency_key": idempotency_key,
            "confirmed_at": payout.confirmed_at,
            "failed_at": payout.failed_at,
            "block_number": payout.block_number,
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



def _resolve_execute_idempotency_key(
    *,
    request: Request,
    profit_month_id: str,
    payload: DistributionExecuteRequest,
) -> str:
    header_key = request.headers.get("Idempotency-Key")
    if header_key:
        return header_key

    if payload.idempotency_key:
        return payload.idempotency_key

    canonical_payload = {
        "profit_month_id": profit_month_id,
        "stakers": payload.stakers,
        "stakerShares": payload.staker_shares,
        "authors": payload.authors,
        "authorShares": payload.author_shares,
    }
    serialized = json.dumps(canonical_payload, separators=(",", ":"), ensure_ascii=True, sort_keys=True)
    body_hash = hashlib.sha256(serialized.encode("utf-8")).hexdigest()
    return f"execute_distribution:{profit_month_id}:{body_hash}"


def _sync_payout_idempotency_key(profit_month_id: str, tx_hash: str) -> str:
    return f"sync_payout:{profit_month_id}:{tx_hash_lower(tx_hash)}"


def _validate_tx_hash_32(tx_hash: str) -> None:
    if not _TX_HASH_32_RE.fullmatch(tx_hash):
        raise HTTPException(status_code=400, detail="tx_hash must be a 0x-prefixed 32-byte hex string")


def tx_hash_lower(tx_hash: str) -> str:
    return tx_hash.lower()


def _latest_payout_for_tx(db: Session, profit_month_id: str, tx_hash: str) -> DividendPayout | None:
    return (
        db.query(DividendPayout)
        .filter(
            DividendPayout.profit_month_id == profit_month_id,
            func.lower(DividendPayout.tx_hash) == tx_hash_lower(tx_hash),
        )
        .order_by(DividendPayout.created_at.desc(), DividendPayout.id.desc())
        .first()
    )


def _latest_payout(db: Session, profit_month_id: str) -> DividendPayout | None:
    return (
        db.query(DividendPayout)
        .filter(DividendPayout.profit_month_id == profit_month_id)
        .order_by(DividendPayout.created_at.desc(), DividendPayout.id.desc())
        .first()
    )


def _discover_payout_tx_hash(db: Session, profit_month_id: str) -> str | None:
    payout = _latest_payout(db, profit_month_id)
    if payout is not None and payout.tx_hash:
        return payout.tx_hash
    return _discover_execution_tx_hash(db, profit_month_id)


def _discover_execution_tx_hash(db: Session, profit_month_id: str) -> str | None:
    execution = (
        db.query(DistributionExecution)
        .filter(
            DistributionExecution.profit_month_id == profit_month_id,
            DistributionExecution.status.in_(["submitted", "already_distributed"]),
            DistributionExecution.tx_hash.isnot(None),
        )
        .order_by(DistributionExecution.created_at.desc(), DistributionExecution.id.desc())
        .first()
    )
    return execution.tx_hash if execution is not None else None


def _blocked_confirm_response(
    request: Request,
    db: Session,
    *,
    profit_month_id: str,
    blocked_reason: str,
    idempotency_key: str,
    tx_hash: str | None,
    status: str,
    error_hint: str | None = None,
) -> PayoutConfirmResponse:
    _record_oracle_audit(
        request,
        db,
        idempotency_key=idempotency_key,
        tx_hash=tx_hash,
        error_hint=error_hint or blocked_reason,
    )
    return PayoutConfirmResponse(
        success=False,
        data={
            "profit_month_id": profit_month_id,
            "status": status,
            "tx_hash": tx_hash,
            "blocked_reason": blocked_reason,
            "idempotency_key": idempotency_key,
            "confirmed_at": None,
            "failed_at": None,
            "block_number": None,
        },
    )


def _blocked_sync_response(
    request: Request,
    db: Session,
    *,
    profit_month_id: str,
    blocked_reason: str,
    idempotency_key: str | None = None,
    tx_hash: str | None = None,
    error_hint: str | None = None,
) -> PayoutSyncResponse:
    resolved_key = idempotency_key or f"sync_payout:{profit_month_id}:blocked:{blocked_reason}"
    _record_oracle_audit(
        request,
        db,
        idempotency_key=resolved_key,
        tx_hash=tx_hash,
        error_hint=error_hint or blocked_reason,
    )
    return PayoutSyncResponse(
        success=False,
        data={
            "profit_month_id": profit_month_id,
            "status": "blocked",
            "tx_hash": tx_hash,
            "blocked_reason": blocked_reason,
            "idempotency_key": resolved_key,
            "executed_at": None,
        },
    )


def _split_distribution_totals(total_profit_micro_usdc: int) -> tuple[int, int, int, int]:
    stakers_total = (total_profit_micro_usdc * 6600) // 10000
    treasury_total = (total_profit_micro_usdc * 1900) // 10000
    authors_total = (total_profit_micro_usdc * 1000) // 10000
    founder_total = (total_profit_micro_usdc * 500) // 10000
    allocated = stakers_total + treasury_total + authors_total + founder_total
    treasury_total += total_profit_micro_usdc - allocated
    return stakers_total, treasury_total, authors_total, founder_total


def _upsert_dividend_payout(
    db: Session,
    *,
    profit_month_id: str,
    idempotency_key: str,
    tx_hash: str,
    total_profit_micro_usdc: int,
    stakers_count: int,
    authors_count: int,
) -> None:
    stakers_total, treasury_total, authors_total, founder_total = _split_distribution_totals(total_profit_micro_usdc)
    if stakers_count == 0:
        treasury_total += stakers_total
        stakers_total = 0
    if authors_count == 0:
        treasury_total += authors_total
        authors_total = 0

    payout = DividendPayout(
        profit_month_id=profit_month_id,
        idempotency_key=idempotency_key,
        status="pending",
        tx_hash=tx_hash,
        stakers_count=stakers_count,
        authors_count=authors_count,
        total_stakers_micro_usdc=stakers_total,
        total_treasury_micro_usdc=treasury_total,
        total_authors_micro_usdc=authors_total,
        total_founder_micro_usdc=founder_total,
        total_payout_micro_usdc=total_profit_micro_usdc,
        payout_executed_at=func.now(),
    )
    _, _ = insert_or_get_by_unique(
        db,
        instance=payout,
        model=DividendPayout,
        unique_filter={"idempotency_key": idempotency_key},
    )




_ADDRESS_RE = re.compile(r"^0x[a-fA-F0-9]{40}$")


def _record_blocked_execution(
    request: Request,
    db: Session,
    *,
    profit_month_id: str,
    idempotency_key: str,
    blocked_reason: str,
    error_hint: str | None = None,
) -> DistributionExecuteResponse:
    execution = DistributionExecution(
        profit_month_id=profit_month_id,
        idempotency_key=idempotency_key,
        status="blocked",
        tx_hash=None,
        blocked_reason=blocked_reason,
    )
    _, _ = insert_or_get_by_unique(
        db,
        instance=execution,
        model=DistributionExecution,
        unique_filter={"idempotency_key": idempotency_key},
    )
    _record_oracle_audit(
        request,
        db,
        idempotency_key=idempotency_key,
        error_hint=error_hint,
        commit=False,
    )
    db.commit()
    return DistributionExecuteResponse(
        success=False,
        data={
            "profit_month_id": profit_month_id,
            "status": "blocked",
            "tx_hash": None,
            "blocked_reason": blocked_reason,
            "idempotency_key": idempotency_key,
        },
    )


def _validate_execute_distribution_payload(payload: DistributionExecuteRequest) -> str | None:
    if len(payload.stakers) > _MAX_STAKERS or len(payload.authors) > _MAX_AUTHORS:
        return "recipient_caps_exceeded"
    if len(payload.stakers) != len(payload.staker_shares) or len(payload.authors) != len(payload.author_shares):
        return "recipient_shares_length_mismatch"

    for address in payload.stakers:
        if not _ADDRESS_RE.fullmatch(address) or address.lower() == "0x0000000000000000000000000000000000000000":
            return "invalid_recipient"
    for address in payload.authors:
        if not _ADDRESS_RE.fullmatch(address) or address.lower() == "0x0000000000000000000000000000000000000000":
            return "invalid_recipient"

    if len(set(address.lower() for address in payload.stakers)) != len(payload.stakers):
        return "duplicate_recipient"
    if len(set(address.lower() for address in payload.authors)) != len(payload.authors):
        return "duplicate_recipient"

    if any(share <= 0 for share in payload.staker_shares):
        return "invalid_shares"
    if any(share <= 0 for share in payload.author_shares):
        return "invalid_shares"

    return None


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
    commit: bool = True,
) -> None:
    body_hash = getattr(request.state, "body_hash", "")
    signature_status = getattr(request.state, "signature_status", "invalid")
    request_id = request.headers.get("X-Request-Id") or request.headers.get("X-Request-ID") or str(uuid4())
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
        commit=commit,
    )


def _validate_month(profit_month_id: str) -> None:
    if not _MONTH_RE.fullmatch(profit_month_id):
        raise HTTPException(status_code=400, detail="profit_month_id must use YYYYMM format")
    month = int(profit_month_id[4:6])
    if month < 1 or month > 12:
        raise HTTPException(status_code=400, detail="profit_month_id month must be 01..12")
