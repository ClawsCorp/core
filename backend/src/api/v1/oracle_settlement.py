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
from src.models.agent import Agent
from src.models.marketing_fee_accrual_event import MarketingFeeAccrualEvent
from src.models.observed_usdc_transfer import ObservedUsdcTransfer
from src.models.project import Project
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
    DistributionExecutePayloadResponse,
    DistributionExecuteRequest,
    DistributionExecuteResponse,
    MarketingFeeDepositResponse,
    PayoutTriggerRequest,
    PayoutTriggerResponse,
    ProfitDepositResponse,
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
    submit_usdc_transfer_tx,
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


@router.post("/settlement/{profit_month_id}/deposit-profit", response_model=ProfitDepositResponse)
def deposit_profit(
    profit_month_id: str,
    request: Request,
    _: str = Depends(require_oracle_hmac),
    db: Session = Depends(get_db),
) -> ProfitDepositResponse:
    """
    Autonomous profit deposit helper:
    if DividendDistributor USDC balance is below computed profit for the month, enqueue/submit a USDC transfer to top it up.

    Fail-closed gates:
    - requires a reconciliation report (contains on-chain balance + delta)
    - deposit allowed only when delta < 0 and profit_sum > 0
    - blocks on rpc_not_configured / rpc_error and on balance_excess (delta > 0)
    """
    _validate_month(profit_month_id)
    settings = get_settings()

    report = _latest_reconciliation(db, profit_month_id)
    if report is None:
        idempotency_key = f"deposit_profit:{profit_month_id}:0"
        _record_oracle_audit(request, db, idempotency_key=idempotency_key)
        return ProfitDepositResponse(
            success=False,
            data={
                "profit_month_id": profit_month_id,
                "status": "blocked",
                "tx_hash": None,
                "blocked_reason": "reconciliation_missing",
                "idempotency_key": idempotency_key,
                "task_id": None,
                "amount_micro_usdc": None,
            },
        )

    if report.blocked_reason in {"rpc_not_configured", "rpc_error"}:
        idempotency_key = f"deposit_profit:{profit_month_id}:{int(report.profit_sum_micro_usdc or 0)}"
        _record_oracle_audit(request, db, idempotency_key=idempotency_key)
        return ProfitDepositResponse(
            success=False,
            data={
                "profit_month_id": profit_month_id,
                "status": "blocked",
                "tx_hash": None,
                "blocked_reason": report.blocked_reason,
                "idempotency_key": idempotency_key,
                "task_id": None,
                "amount_micro_usdc": None,
            },
        )

    profit_sum = int(report.profit_sum_micro_usdc or 0)
    if profit_sum <= 0:
        idempotency_key = f"deposit_profit:{profit_month_id}:{profit_sum}"
        _record_oracle_audit(request, db, idempotency_key=idempotency_key)
        return ProfitDepositResponse(
            success=False,
            data={
                "profit_month_id": profit_month_id,
                "status": "blocked",
                "tx_hash": None,
                "blocked_reason": "profit_required",
                "idempotency_key": idempotency_key,
                "task_id": None,
                "amount_micro_usdc": None,
            },
        )

    delta = int(report.delta_micro_usdc or 0)  # balance - profit
    if delta == 0:
        idempotency_key = f"deposit_profit:{profit_month_id}:0"
        _record_oracle_audit(request, db, idempotency_key=idempotency_key)
        return ProfitDepositResponse(
            success=False,
            data={
                "profit_month_id": profit_month_id,
                "status": "blocked",
                "tx_hash": None,
                "blocked_reason": "already_funded",
                "idempotency_key": idempotency_key,
                "task_id": None,
                "amount_micro_usdc": 0,
            },
        )
    if delta > 0:
        idempotency_key = f"deposit_profit:{profit_month_id}:0"
        _record_oracle_audit(request, db, idempotency_key=idempotency_key)
        return ProfitDepositResponse(
            success=False,
            data={
                "profit_month_id": profit_month_id,
                "status": "blocked",
                "tx_hash": None,
                "blocked_reason": "balance_excess",
                "idempotency_key": idempotency_key,
                "task_id": None,
                "amount_micro_usdc": None,
            },
        )

    amount = -delta
    idempotency_key = f"deposit_profit:{profit_month_id}:{amount}"

    existing_task = (
        db.query(TxOutbox)
        .filter(TxOutbox.idempotency_key == idempotency_key)
        .order_by(TxOutbox.id.desc())
        .first()
    )
    if existing_task is not None:
        _record_oracle_audit(request, db, idempotency_key=idempotency_key, tx_hash=existing_task.tx_hash)
        return ProfitDepositResponse(
            success=True,
            data={
                "profit_month_id": profit_month_id,
                "status": "submitted",
                "tx_hash": existing_task.tx_hash,
                "blocked_reason": None,
                "idempotency_key": idempotency_key,
                "task_id": existing_task.task_id,
                "amount_micro_usdc": amount,
            },
        )

    distributor_address = settings.dividend_distributor_contract_address
    if distributor_address is None:
        _record_oracle_audit(request, db, idempotency_key=idempotency_key)
        return ProfitDepositResponse(
            success=False,
            data={
                "profit_month_id": profit_month_id,
                "status": "blocked",
                "tx_hash": None,
                "blocked_reason": "missing_distributor_address",
                "idempotency_key": idempotency_key,
                "task_id": None,
                "amount_micro_usdc": amount,
            },
        )

    if settings.tx_outbox_enabled:
        task = enqueue_tx_outbox_task(
            db,
            task_type="deposit_profit",
            payload={
                "profit_month_id": profit_month_id,
                "amount_micro_usdc": amount,
                "to_address": distributor_address,
                "idempotency_key": idempotency_key,
            },
            idempotency_key=idempotency_key,
        )
        _record_oracle_audit(request, db, idempotency_key=idempotency_key, commit=False)
        db.commit()
        db.refresh(task)
        return ProfitDepositResponse(
            success=True,
            data={
                "profit_month_id": profit_month_id,
                "status": "submitted",
                "tx_hash": task.tx_hash,
                "blocked_reason": None,
                "idempotency_key": idempotency_key,
                "task_id": task.task_id,
                "amount_micro_usdc": amount,
            },
        )

    try:
        tx_hash = submit_usdc_transfer_tx(to_address=distributor_address, amount_micro_usdc=amount)
    except BlockchainConfigError as exc:
        blocked_reason = "signer_key_required" if "ORACLE_SIGNER_PRIVATE_KEY" in str(exc) else "rpc_not_configured"
        _record_oracle_audit(request, db, idempotency_key=idempotency_key)
        return ProfitDepositResponse(
            success=False,
            data={
                "profit_month_id": profit_month_id,
                "status": "blocked",
                "tx_hash": None,
                "blocked_reason": blocked_reason,
                "idempotency_key": idempotency_key,
                "task_id": None,
                "amount_micro_usdc": amount,
            },
        )
    except BlockchainTxError as exc:
        _record_oracle_audit(request, db, idempotency_key=idempotency_key, error_hint=exc.error_hint)
        return ProfitDepositResponse(
            success=False,
            data={
                "profit_month_id": profit_month_id,
                "status": "blocked",
                "tx_hash": None,
                "blocked_reason": "tx_error",
                "idempotency_key": idempotency_key,
                "task_id": None,
                "amount_micro_usdc": amount,
            },
        )

    _record_oracle_audit(request, db, idempotency_key=idempotency_key, tx_hash=tx_hash)
    return ProfitDepositResponse(
        success=True,
        data={
            "profit_month_id": profit_month_id,
            "status": "submitted",
            "tx_hash": tx_hash,
            "blocked_reason": None,
            "idempotency_key": idempotency_key,
            "task_id": None,
            "amount_micro_usdc": amount,
        },
    )


@router.post("/marketing/settlement/deposit", response_model=MarketingFeeDepositResponse)
def deposit_marketing_fee_reserve(
    request: Request,
    _: str = Depends(require_oracle_hmac),
    db: Session = Depends(get_db),
) -> MarketingFeeDepositResponse:
    settings = get_settings()

    accrued_total = int(
        db.query(func.coalesce(func.sum(MarketingFeeAccrualEvent.fee_amount_micro_usdc), 0)).scalar() or 0
    )
    sent_rows = (
        db.query(TxOutbox.payload_json)
        .filter(
            TxOutbox.task_type == "deposit_marketing_fee",
            TxOutbox.status.in_(["pending", "processing", "succeeded"]),
        )
        .all()
    )
    sent_total = 0
    for (payload_json,) in sent_rows:
        try:
            payload = json.loads(payload_json or "{}")
            sent_total += int(payload.get("amount_micro_usdc") or 0)
        except (TypeError, ValueError, json.JSONDecodeError):
            continue
    amount = int(accrued_total - sent_total)
    idempotency_key = f"deposit_marketing_fee:{accrued_total}:{sent_total}"

    marketing_treasury = (settings.marketing_treasury_address or "").strip()
    if not marketing_treasury:
        _record_oracle_audit(request, db, idempotency_key=idempotency_key)
        return MarketingFeeDepositResponse(
            success=False,
            data={
                "status": "blocked",
                "tx_hash": None,
                "blocked_reason": "marketing_treasury_missing",
                "idempotency_key": idempotency_key,
                "task_id": None,
                "amount_micro_usdc": None,
                "accrued_total_micro_usdc": accrued_total,
                "sent_total_micro_usdc": sent_total,
            },
        )

    if amount <= 0:
        _record_oracle_audit(request, db, idempotency_key=idempotency_key)
        return MarketingFeeDepositResponse(
            success=False,
            data={
                "status": "blocked",
                "tx_hash": None,
                "blocked_reason": "already_funded",
                "idempotency_key": idempotency_key,
                "task_id": None,
                "amount_micro_usdc": 0,
                "accrued_total_micro_usdc": accrued_total,
                "sent_total_micro_usdc": sent_total,
            },
        )

    existing_task = (
        db.query(TxOutbox)
        .filter(TxOutbox.idempotency_key == idempotency_key)
        .order_by(TxOutbox.id.desc())
        .first()
    )
    if existing_task is not None:
        _record_oracle_audit(request, db, idempotency_key=idempotency_key, tx_hash=existing_task.tx_hash)
        return MarketingFeeDepositResponse(
            success=True,
            data={
                "status": "submitted",
                "tx_hash": existing_task.tx_hash,
                "blocked_reason": None,
                "idempotency_key": idempotency_key,
                "task_id": existing_task.task_id,
                "amount_micro_usdc": amount,
                "accrued_total_micro_usdc": accrued_total,
                "sent_total_micro_usdc": sent_total,
            },
        )

    if settings.tx_outbox_enabled:
        task = enqueue_tx_outbox_task(
            db,
            task_type="deposit_marketing_fee",
            payload={
                "amount_micro_usdc": amount,
                "to_address": marketing_treasury,
                "idempotency_key": idempotency_key,
            },
            idempotency_key=idempotency_key,
        )
        _record_oracle_audit(request, db, idempotency_key=idempotency_key, commit=False)
        db.commit()
        db.refresh(task)
        return MarketingFeeDepositResponse(
            success=True,
            data={
                "status": "submitted",
                "tx_hash": task.tx_hash,
                "blocked_reason": None,
                "idempotency_key": idempotency_key,
                "task_id": task.task_id,
                "amount_micro_usdc": amount,
                "accrued_total_micro_usdc": accrued_total,
                "sent_total_micro_usdc": sent_total,
            },
        )

    try:
        tx_hash = submit_usdc_transfer_tx(to_address=marketing_treasury, amount_micro_usdc=amount)
    except BlockchainConfigError as exc:
        blocked_reason = "signer_key_required" if "ORACLE_SIGNER_PRIVATE_KEY" in str(exc) else "rpc_not_configured"
        _record_oracle_audit(request, db, idempotency_key=idempotency_key)
        return MarketingFeeDepositResponse(
            success=False,
            data={
                "status": "blocked",
                "tx_hash": None,
                "blocked_reason": blocked_reason,
                "idempotency_key": idempotency_key,
                "task_id": None,
                "amount_micro_usdc": amount,
                "accrued_total_micro_usdc": accrued_total,
                "sent_total_micro_usdc": sent_total,
            },
        )
    except BlockchainTxError as exc:
        _record_oracle_audit(request, db, idempotency_key=idempotency_key, error_hint=exc.error_hint)
        return MarketingFeeDepositResponse(
            success=False,
            data={
                "status": "blocked",
                "tx_hash": None,
                "blocked_reason": "tx_error",
                "idempotency_key": idempotency_key,
                "task_id": None,
                "amount_micro_usdc": amount,
                "accrued_total_micro_usdc": accrued_total,
                "sent_total_micro_usdc": sent_total,
            },
        )

    _record_oracle_audit(request, db, idempotency_key=idempotency_key, tx_hash=tx_hash)
    return MarketingFeeDepositResponse(
        success=True,
        data={
            "status": "submitted",
            "tx_hash": tx_hash,
            "blocked_reason": None,
            "idempotency_key": idempotency_key,
            "task_id": None,
            "amount_micro_usdc": amount,
            "accrued_total_micro_usdc": accrued_total,
            "sent_total_micro_usdc": sent_total,
        },
    )


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
            if existing_task.status == "blocked":
                _record_oracle_audit(request, db, idempotency_key=idempotency_key)
                return DistributionCreateResponse(
                    success=False,
                    data={
                        "profit_month_id": profit_month_id,
                        "status": "blocked",
                        "tx_hash": existing_task.tx_hash,
                        "blocked_reason": existing_task.last_error_hint or "tx_blocked",
                        "idempotency_key": idempotency_key,
                        "task_id": existing_task.task_id,
                    },
                )
            if existing_task.status == "failed":
                _record_oracle_audit(request, db, idempotency_key=idempotency_key)
                return DistributionCreateResponse(
                    success=False,
                    data={
                        "profit_month_id": profit_month_id,
                        "status": "blocked",
                        "tx_hash": existing_task.tx_hash,
                        "blocked_reason": existing_task.last_error_hint or "tx_failed",
                        "idempotency_key": idempotency_key,
                        "task_id": existing_task.task_id,
                    },
                )
            if existing_task.status == "succeeded":
                _record_oracle_audit(request, db, idempotency_key=idempotency_key, tx_hash=existing_task.tx_hash)
                return DistributionCreateResponse(
                    success=True,
                    data={
                        "profit_month_id": profit_month_id,
                        "status": "submitted",
                        "tx_hash": existing_task.tx_hash,
                        "blocked_reason": None,
                        "idempotency_key": idempotency_key,
                        "task_id": existing_task.task_id,
                    },
                )
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

    if (settings.safe_owner_address or "").strip():
        _record_oracle_audit(request, db, idempotency_key=idempotency_key)
        return DistributionCreateResponse(
            success=False,
            data={
                "profit_month_id": profit_month_id,
                "status": "blocked",
                "tx_hash": None,
                "blocked_reason": "safe_execution_required",
                "idempotency_key": idempotency_key,
                "task_id": None,
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


def _build_execute_distribution_payload(
    db: Session, *, profit_month_id: str
) -> tuple[list[str], list[int], list[str], list[int], list[str], str | None]:
    # Stakers bucket: derive from net USDC movement into/out of FundingPool (if configured).
    # If stakers end up empty, stakers bucket is routed to treasury on-chain.
    stakers: list[str] = []
    staker_shares: list[int] = []
    notes: list[str] = []
    stakers_blocked_reason: str | None = None

    settings = get_settings()
    pool_addr = (settings.funding_pool_contract_address or "").strip().lower()
    if not pool_addr:
        notes.append("stakers_source_missing_routes_stakers_to_treasury")
    elif not _ADDRESS_RE.fullmatch(pool_addr) or pool_addr == "0x0000000000000000000000000000000000000000":
        stakers_blocked_reason = "funding_pool_address_invalid"
    else:
        notes.append("stakers_from_funding_pool_observed_transfers")
        in_rows = (
            db.query(
                ObservedUsdcTransfer.from_address,
                func.sum(ObservedUsdcTransfer.amount_micro_usdc).label("amount_sum"),
            )
            .filter(ObservedUsdcTransfer.to_address == pool_addr)
            .group_by(ObservedUsdcTransfer.from_address)
            .all()
        )
        out_rows = (
            db.query(
                ObservedUsdcTransfer.to_address,
                func.sum(ObservedUsdcTransfer.amount_micro_usdc).label("amount_sum"),
            )
            .filter(ObservedUsdcTransfer.from_address == pool_addr)
            .group_by(ObservedUsdcTransfer.to_address)
            .all()
        )

        net_by_address: dict[str, int] = {}
        for addr, amount_sum in in_rows:
            a = str(addr).lower()
            net_by_address[a] = net_by_address.get(a, 0) + int(amount_sum or 0)
        for addr, amount_sum in out_rows:
            a = str(addr).lower()
            net_by_address[a] = net_by_address.get(a, 0) - int(amount_sum or 0)

        negatives = [a for a, v in net_by_address.items() if int(v) < 0]
        if negatives:
            stakers_blocked_reason = "stakers_negative_balance"
        else:
            items = [(a, int(v)) for a, v in net_by_address.items() if int(v) > 0]
            items = sorted(items, key=lambda kv: (-int(kv[1]), kv[0]))
            if len(items) > _MAX_STAKERS:
                notes.append(f"stakers_capped_to_{_MAX_STAKERS}")
                items = items[:_MAX_STAKERS]
            stakers = [a for a, _v in items]
            staker_shares = [int(v) for _a, v in items]
            if not stakers:
                notes.append("no_stakers_detected_routes_stakers_to_treasury")

    # Authors bucket: originators of projects that generated positive profit for the month.
    rev_rows = (
        db.query(RevenueEvent.project_id, func.sum(RevenueEvent.amount_micro_usdc))
        .filter(
            RevenueEvent.profit_month_id == profit_month_id,
            RevenueEvent.project_id.isnot(None),
        )
        .group_by(RevenueEvent.project_id)
        .all()
    )
    exp_rows = (
        db.query(ExpenseEvent.project_id, func.sum(ExpenseEvent.amount_micro_usdc))
        .filter(
            ExpenseEvent.profit_month_id == profit_month_id,
            ExpenseEvent.project_id.isnot(None),
        )
        .group_by(ExpenseEvent.project_id)
        .all()
    )

    profit_by_project_pk: dict[int, int] = {}
    for project_pk, amount_sum in rev_rows:
        if project_pk is None:
            continue
        profit_by_project_pk[int(project_pk)] = profit_by_project_pk.get(int(project_pk), 0) + int(amount_sum or 0)
    for project_pk, amount_sum in exp_rows:
        if project_pk is None:
            continue
        profit_by_project_pk[int(project_pk)] = profit_by_project_pk.get(int(project_pk), 0) - int(amount_sum or 0)

    positive_project_pks = [pk for pk, profit in profit_by_project_pk.items() if int(profit) > 0]
    if not positive_project_pks:
        notes.append("no_positive_profit_projects_for_month")
        return stakers, staker_shares, [], [], notes, stakers_blocked_reason

    projects = (
        db.query(Project.id, Project.project_id, Project.originator_agent_id)
        .filter(Project.id.in_(positive_project_pks))
        .all()
    )
    originator_pks = sorted({int(p.originator_agent_id) for p in projects if p.originator_agent_id is not None})
    agents = (
        db.query(Agent.id, Agent.wallet_address)
        .filter(Agent.id.in_(originator_pks))
        .all()
    )
    wallet_by_agent_pk: dict[int, str | None] = {int(a.id): a.wallet_address for a in agents}

    # Accumulate weights by wallet address (one agent may have multiple projects).
    weight_by_wallet: dict[str, int] = {}
    missing_wallet_agents: set[int] = set()
    invalid_wallet_agents: set[int] = set()

    for proj_pk, _proj_id, originator_pk in projects:
        if originator_pk is None:
            continue
        profit = int(profit_by_project_pk.get(int(proj_pk), 0))
        if profit <= 0:
            continue
        wallet = (wallet_by_agent_pk.get(int(originator_pk)) or "").strip()
        if not wallet:
            missing_wallet_agents.add(int(originator_pk))
            continue
        if not _ADDRESS_RE.fullmatch(wallet) or wallet.lower() == "0x0000000000000000000000000000000000000000":
            invalid_wallet_agents.add(int(originator_pk))
            continue
        w = wallet.lower()
        weight_by_wallet[w] = weight_by_wallet.get(w, 0) + profit

    if missing_wallet_agents:
        notes.append("some_originators_missing_wallet_address")
    if invalid_wallet_agents:
        notes.append("some_originators_have_invalid_wallet_address")

    # Deterministic ordering; apply caps as MVP compromise.
    items = sorted(weight_by_wallet.items(), key=lambda kv: (-int(kv[1]), kv[0]))
    if len(items) > _MAX_AUTHORS:
        notes.append(f"authors_capped_to_{_MAX_AUTHORS}")
        items = items[:_MAX_AUTHORS]

    authors = [addr for addr, _weight in items]
    author_shares = [int(weight) if int(weight) > 0 else 1 for _addr, weight in items]

    # Ensure strictly positive shares (contract requires totalShares > 0 and per-share used for payout math).
    author_shares = [max(1, int(s)) for s in author_shares]

    return stakers, staker_shares, authors, author_shares, notes, stakers_blocked_reason


@router.post(
    "/distributions/{profit_month_id}/execute/payload",
    response_model=DistributionExecutePayloadResponse,
)
def build_execute_distribution_payload(
    profit_month_id: str,
    request: Request,
    _: str = Depends(require_oracle_hmac),
    db: Session = Depends(get_db),
) -> DistributionExecutePayloadResponse:
    _validate_month(profit_month_id)

    blocked_reason: str | None = None
    settlement = _latest_settlement(db, profit_month_id)
    if settlement is None:
        blocked_reason = "missing_settlement"
    elif settlement.profit_sum_micro_usdc <= 0:
        blocked_reason = "profit_required"

    report = _latest_reconciliation(db, profit_month_id)
    if report is None:
        blocked_reason = blocked_reason or "reconciliation_missing"
    elif not report.ready or report.delta_micro_usdc != 0:
        blocked_reason = blocked_reason or "not_ready"

    stakers, staker_shares, authors, author_shares, notes, stakers_blocked_reason = _build_execute_distribution_payload(
        db, profit_month_id=profit_month_id
    )
    if stakers_blocked_reason is not None:
        blocked_reason = blocked_reason or stakers_blocked_reason

    # Basic validation parity: if we generated a payload that would be rejected, mark as blocked.
    validation_error = _validate_execute_distribution_payload(
        DistributionExecuteRequest(
            stakers=stakers,
            staker_shares=staker_shares,
            authors=authors,
            author_shares=author_shares,
        )
    )
    if validation_error is not None:
        blocked_reason = blocked_reason or validation_error

    # Audit as oracle read-style action.
    _record_oracle_audit(
        request,
        db,
        idempotency_key=f"execute_payload:{profit_month_id}",
        error_hint=blocked_reason,
        commit=False,
    )
    db.commit()

    ok = blocked_reason is None
    return DistributionExecutePayloadResponse(
        success=ok,
        data={
            "profit_month_id": profit_month_id,
            "status": "ok" if ok else "blocked",
            "blocked_reason": blocked_reason,
            "stakers": stakers,
            "staker_shares": staker_shares,
            "authors": authors,
            "author_shares": author_shares,
            "notes": notes,
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
            if existing_task.status == "blocked":
                _record_oracle_audit(request, db, idempotency_key=idempotency_key)
                return DistributionExecuteResponse(
                    success=False,
                    data={
                        "profit_month_id": profit_month_id,
                        "status": "blocked",
                        "tx_hash": existing_task.tx_hash,
                        "blocked_reason": existing_task.last_error_hint or "tx_blocked",
                        "idempotency_key": idempotency_key,
                        "task_id": existing_task.task_id,
                    },
                )
            if existing_task.status == "failed":
                _record_oracle_audit(request, db, idempotency_key=idempotency_key)
                return DistributionExecuteResponse(
                    success=False,
                    data={
                        "profit_month_id": profit_month_id,
                        "status": "blocked",
                        "tx_hash": existing_task.tx_hash,
                        "blocked_reason": existing_task.last_error_hint or "tx_failed",
                        "idempotency_key": idempotency_key,
                        "task_id": existing_task.task_id,
                    },
                )
            if existing_task.status == "succeeded":
                _record_oracle_audit(request, db, idempotency_key=idempotency_key, tx_hash=existing_task.tx_hash)
                return DistributionExecuteResponse(
                    success=True,
                    data={
                        "profit_month_id": profit_month_id,
                        "status": "submitted",
                        "tx_hash": existing_task.tx_hash,
                        "blocked_reason": None,
                        "idempotency_key": idempotency_key,
                        "task_id": existing_task.task_id,
                    },
                )
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

    if (settings.safe_owner_address or "").strip():
        return _record_blocked_execution(
            request,
            db,
            profit_month_id=profit_month_id,
            idempotency_key=idempotency_key,
            blocked_reason="safe_execution_required",
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
    if len(payload.stakers) + len(payload.authors) == 0:
        return "recipients_required"
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
