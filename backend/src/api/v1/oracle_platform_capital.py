from __future__ import annotations

import re
import secrets
from datetime import datetime, timezone
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from src.api.v1.dependencies import require_oracle_hmac
from src.core.audit import record_audit
from src.core.config import get_settings
from src.core.database import get_db
from src.core.db_utils import insert_or_get_by_unique
from src.models.marketing_fee_accrual_event import MarketingFeeAccrualEvent
from src.models.observed_usdc_transfer import ObservedUsdcTransfer
from src.models.platform_capital_event import PlatformCapitalEvent
from src.models.platform_capital_reconciliation_report import PlatformCapitalReconciliationReport
from src.schemas.platform_capital import (
    PlatformCapitalEventCreateRequest,
    PlatformCapitalEventDetailResponse,
    PlatformCapitalEventPublic,
    PlatformCapitalReconciliationReportPublic,
    PlatformCapitalReconciliationRunResponse,
    PlatformCapitalSummaryData,
    PlatformCapitalSummaryResponse,
    PlatformCapitalSyncData,
    PlatformCapitalSyncResponse,
)
from src.services.blockchain import (
    BlockchainConfigError,
    BlockchainReadError,
    get_usdc_balance_micro_usdc,
    read_block_timestamp_utc,
)
from src.services.marketing_fee import (
    accrue_marketing_fee_event,
    build_marketing_fee_idempotency_key,
    calculate_marketing_fee_micro_usdc,
)
from src.services.platform_capital import (
    get_latest_platform_capital_reconciliation,
    get_platform_capital_balance_micro_usdc,
    get_platform_capital_spendable_balance_micro_usdc,
    is_reconciliation_fresh,
)

router = APIRouter(prefix="/api/v1", tags=["platform-capital"])

_MONTH_RE = re.compile(r"^\d{6}$")
_ADDRESS_RE = re.compile(r"^0x[a-f0-9]{40}$")


@router.post("/oracle/platform-capital-events", response_model=PlatformCapitalEventDetailResponse, tags=["oracle-platform-capital"])
async def create_platform_capital_event(
    payload: PlatformCapitalEventCreateRequest,
    request: Request,
    _: str = Depends(require_oracle_hmac),
    db: Session = Depends(get_db),
) -> PlatformCapitalEventDetailResponse:
    if payload.profit_month_id is not None:
        _validate_month(payload.profit_month_id)
    if int(payload.delta_micro_usdc) == 0:
        raise HTTPException(status_code=400, detail="delta_micro_usdc must be non-zero")

    request_id = request.headers.get("X-Request-Id") or request.headers.get("X-Request-ID") or str(uuid4())
    body_hash = request.state.body_hash

    if int(payload.delta_micro_usdc) < 0:
        blocked_reason = _ensure_platform_capital_outflow_reconciliation_gate(db)
        if blocked_reason is not None:
            _record_oracle_audit(
                request,
                db,
                body_hash,
                request_id,
                payload.idempotency_key,
                error_hint=(
                    f"br={blocked_reason};idem={payload.idempotency_key};"
                    f"d={int(payload.delta_micro_usdc)};src={payload.source}"
                )[:255],
                commit=False,
            )
            db.commit()
            return PlatformCapitalEventDetailResponse(success=False, data=None, blocked_reason=blocked_reason)

    event = PlatformCapitalEvent(
        event_id=_generate_event_id(db),
        idempotency_key=payload.idempotency_key,
        profit_month_id=payload.profit_month_id,
        delta_micro_usdc=int(payload.delta_micro_usdc),
        source=payload.source,
        evidence_tx_hash=payload.evidence_tx_hash.lower() if payload.evidence_tx_hash else None,
        evidence_url=payload.evidence_url,
    )
    event, _created = insert_or_get_by_unique(
        db,
        instance=event,
        model=PlatformCapitalEvent,
        unique_filter={"idempotency_key": payload.idempotency_key},
    )
    if int(event.delta_micro_usdc) > 0:
        accrue_marketing_fee_event(
            db,
            idempotency_key=build_marketing_fee_idempotency_key(
                prefix="mfee:platform_capital_event",
                source_idempotency_key=payload.idempotency_key,
            ),
            project_id=None,
            profit_month_id=payload.profit_month_id,
            bucket="platform_capital",
            source=payload.source,
            gross_amount_micro_usdc=int(event.delta_micro_usdc),
            chain_id=None,
            tx_hash=event.evidence_tx_hash,
            log_index=None,
            evidence_url=payload.evidence_url or f"platform_capital_event:{payload.idempotency_key}",
        )
    _record_oracle_audit(request, db, body_hash, request_id, payload.idempotency_key, commit=False)
    db.commit()
    db.refresh(event)
    return PlatformCapitalEventDetailResponse(success=True, data=_public_event(event), blocked_reason=None)


@router.post("/oracle/platform-capital-events/sync", response_model=PlatformCapitalSyncResponse, tags=["oracle-platform-capital"])
async def sync_platform_capital_from_observed_usdc_transfers(
    request: Request,
    _: str = Depends(require_oracle_hmac),
    db: Session = Depends(get_db),
) -> PlatformCapitalSyncResponse:
    settings = get_settings()
    funding_pool_address = (settings.funding_pool_contract_address or "").strip().lower()
    request_id = request.headers.get("X-Request-Id") or request.headers.get("X-Request-ID") or str(uuid4())
    body_hash = request.state.body_hash
    sync_idem = request.headers.get("Idempotency-Key") or f"platform_capital_sync:{request_id}"

    if not funding_pool_address or not _ADDRESS_RE.fullmatch(funding_pool_address):
        _record_oracle_audit(request, db, body_hash, request_id, sync_idem, commit=True)
        return PlatformCapitalSyncResponse(
            success=True,
            data=PlatformCapitalSyncData(
                transfers_seen=0,
                capital_events_inserted=0,
                marketing_fee_events_inserted=0,
                marketing_fee_total_micro_usdc=0,
            ),
        )

    transfers = (
        db.query(ObservedUsdcTransfer)
        .filter(
            ObservedUsdcTransfer.to_address == funding_pool_address,
            ObservedUsdcTransfer.from_address != funding_pool_address,
        )
        .order_by(ObservedUsdcTransfer.block_number.desc(), ObservedUsdcTransfer.log_index.desc())
        .limit(1000)
        .all()
    )

    block_ts_cache: dict[int, str] = {}
    inserted = 0
    marketing_fee_events_inserted = 0
    marketing_fee_total_micro_usdc = 0

    for transfer in transfers:
        bn = int(transfer.block_number)
        if bn in block_ts_cache:
            profit_month_id = block_ts_cache[bn]
        else:
            try:
                ts = read_block_timestamp_utc(bn)
                profit_month_id = ts.astimezone(timezone.utc).strftime("%Y%m")
            except BlockchainReadError:
                profit_month_id = transfer.observed_at.astimezone(timezone.utc).strftime("%Y%m")
            block_ts_cache[bn] = profit_month_id

        tx_hash_lc = str(transfer.tx_hash).lower()
        amount_micro_usdc = int(transfer.amount_micro_usdc)
        already_accounted = (
            db.query(PlatformCapitalEvent.id)
            .filter(
                PlatformCapitalEvent.evidence_tx_hash == tx_hash_lc,
                PlatformCapitalEvent.delta_micro_usdc == amount_micro_usdc,
            )
            .first()
        )
        created = False
        if already_accounted is None:
            idem = (
                f"platcap:deposit:{int(transfer.chain_id)}:{tx_hash_lc}:{int(transfer.log_index)}"
                f":to:funding_pool"
            )
            event = PlatformCapitalEvent(
                event_id=_generate_event_id(db),
                idempotency_key=idem,
                profit_month_id=profit_month_id,
                delta_micro_usdc=amount_micro_usdc,
                source="funding_pool_usdc_deposit",
                evidence_tx_hash=tx_hash_lc,
                evidence_url=f"usdc_transfer:{tx_hash_lc}#log:{int(transfer.log_index)};to:funding_pool",
            )
            _row, created = insert_or_get_by_unique(
                db,
                instance=event,
                model=PlatformCapitalEvent,
                unique_filter={"idempotency_key": idem},
            )
            if created:
                inserted += 1

        expected_fee = calculate_marketing_fee_micro_usdc(amount_micro_usdc)
        existing_mfee = (
            db.query(MarketingFeeAccrualEvent)
            .filter(
                MarketingFeeAccrualEvent.project_id.is_(None),
                MarketingFeeAccrualEvent.bucket == "platform_capital",
                MarketingFeeAccrualEvent.tx_hash == tx_hash_lc,
                MarketingFeeAccrualEvent.log_index == int(transfer.log_index),
                MarketingFeeAccrualEvent.gross_amount_micro_usdc == amount_micro_usdc,
                MarketingFeeAccrualEvent.fee_amount_micro_usdc == expected_fee,
            )
            .first()
        )
        if existing_mfee is not None:
            marketing_fee_total_micro_usdc += int(existing_mfee.fee_amount_micro_usdc)
        elif created:
            _mfee_row, mfee_created, mfee_amount = accrue_marketing_fee_event(
                db,
                idempotency_key=(
                    f"mfee:platform_capital_sync:{int(transfer.chain_id)}:{tx_hash_lc}:{int(transfer.log_index)}"
                ),
                project_id=None,
                profit_month_id=profit_month_id,
                bucket="platform_capital",
                source="funding_pool_usdc_deposit",
                gross_amount_micro_usdc=amount_micro_usdc,
                chain_id=int(transfer.chain_id),
                tx_hash=tx_hash_lc,
                log_index=int(transfer.log_index),
                evidence_url=f"usdc_transfer:{tx_hash_lc}#log:{int(transfer.log_index)};to:funding_pool",
            )
            if mfee_created:
                marketing_fee_events_inserted += 1
            marketing_fee_total_micro_usdc += int(mfee_amount)

    _record_oracle_audit(request, db, body_hash, request_id, sync_idem, commit=False)
    db.commit()
    return PlatformCapitalSyncResponse(
        success=True,
        data=PlatformCapitalSyncData(
            transfers_seen=len(transfers),
            capital_events_inserted=inserted,
            marketing_fee_events_inserted=marketing_fee_events_inserted,
            marketing_fee_total_micro_usdc=marketing_fee_total_micro_usdc,
        ),
    )


@router.post("/oracle/platform-capital/reconciliation", response_model=PlatformCapitalReconciliationRunResponse, tags=["oracle-platform-capital"])
async def reconcile_platform_capital(
    request: Request,
    _: str = Depends(require_oracle_hmac),
    db: Session = Depends(get_db),
) -> PlatformCapitalReconciliationRunResponse:
    settings = get_settings()
    funding_pool_address = (settings.funding_pool_contract_address or "").strip().lower()
    request_id = request.headers.get("X-Request-Id") or request.headers.get("X-Request-ID") or str(uuid4())
    body_hash = request.state.body_hash
    idempotency_key = f"platform_capital_reconciliation:{request_id}"

    if not funding_pool_address or not _ADDRESS_RE.fullmatch(funding_pool_address):
        report = PlatformCapitalReconciliationReport(
            funding_pool_address="",
            ledger_balance_micro_usdc=None,
            onchain_balance_micro_usdc=None,
            delta_micro_usdc=None,
            ready=False,
            blocked_reason="funding_pool_not_configured"
            if not funding_pool_address
            else "funding_pool_invalid",
        )
        db.add(report)
        _record_oracle_audit(request, db, body_hash, request_id, idempotency_key, commit=False)
        db.commit()
        db.refresh(report)
        return PlatformCapitalReconciliationRunResponse(success=True, data=_public_reconciliation(report))

    ledger_balance = get_platform_capital_balance_micro_usdc(db)
    try:
        onchain = get_usdc_balance_micro_usdc(funding_pool_address)
    except BlockchainConfigError:
        report = PlatformCapitalReconciliationReport(
            funding_pool_address=funding_pool_address,
            ledger_balance_micro_usdc=None,
            onchain_balance_micro_usdc=None,
            delta_micro_usdc=None,
            ready=False,
            blocked_reason="rpc_not_configured",
        )
    except BlockchainReadError:
        report = PlatformCapitalReconciliationReport(
            funding_pool_address=funding_pool_address,
            ledger_balance_micro_usdc=None,
            onchain_balance_micro_usdc=None,
            delta_micro_usdc=None,
            ready=False,
            blocked_reason="rpc_error",
        )
    else:
        delta = int(onchain.balance_micro_usdc) - int(ledger_balance)
        ready = delta == 0 and int(ledger_balance) >= 0
        report = PlatformCapitalReconciliationReport(
            funding_pool_address=funding_pool_address,
            ledger_balance_micro_usdc=int(ledger_balance),
            onchain_balance_micro_usdc=int(onchain.balance_micro_usdc),
            delta_micro_usdc=int(delta),
            ready=ready,
            blocked_reason=None if ready else "balance_mismatch",
        )

    db.add(report)
    _record_oracle_audit(request, db, body_hash, request_id, idempotency_key, commit=False)
    db.commit()
    db.refresh(report)
    return PlatformCapitalReconciliationRunResponse(success=True, data=_public_reconciliation(report))


@router.get("/platform-capital/reconciliation/latest", response_model=PlatformCapitalReconciliationRunResponse, tags=["public-platform-capital"])
def get_latest_platform_capital_reconciliation_report(
    db: Session = Depends(get_db),
) -> PlatformCapitalReconciliationRunResponse:
    latest = get_latest_platform_capital_reconciliation(db)
    if latest is None:
        raise HTTPException(status_code=404, detail="Platform capital reconciliation not found")
    return PlatformCapitalReconciliationRunResponse(success=True, data=_public_reconciliation(latest))


@router.get("/platform-capital/summary", response_model=PlatformCapitalSummaryResponse, tags=["public-platform-capital"])
def get_platform_capital_summary(
    db: Session = Depends(get_db),
) -> PlatformCapitalSummaryResponse:
    settings = get_settings()
    latest = get_latest_platform_capital_reconciliation(db)
    return PlatformCapitalSummaryResponse(
        success=True,
        data=PlatformCapitalSummaryData(
            funding_pool_address=settings.funding_pool_contract_address,
            ledger_balance_micro_usdc=get_platform_capital_balance_micro_usdc(db),
            spendable_balance_micro_usdc=get_platform_capital_spendable_balance_micro_usdc(db),
            latest_reconciliation=_public_reconciliation(latest) if latest is not None else None,
            blocked_reason=(
                "funding_pool_address_missing"
                if not (settings.funding_pool_contract_address or "").strip()
                else "funding_pool_address_invalid"
                if not _ADDRESS_RE.fullmatch(str(settings.funding_pool_contract_address).lower())
                else None
            )
        ),
    )


def _validate_month(profit_month_id: str) -> None:
    if not _MONTH_RE.fullmatch(profit_month_id):
        raise HTTPException(status_code=400, detail="profit_month_id must use YYYYMM format")
    month = int(profit_month_id[4:6])
    if month < 1 or month > 12:
        raise HTTPException(status_code=400, detail="profit_month_id month must be 01..12")


def _generate_event_id(db: Session) -> str:
    for _ in range(5):
        candidate = f"platcap_{secrets.token_hex(8)}"
        if db.query(PlatformCapitalEvent.id).filter(PlatformCapitalEvent.event_id == candidate).first() is None:
            return candidate
    raise RuntimeError("Failed to generate unique platform capital event id.")


def _ensure_platform_capital_outflow_reconciliation_gate(db: Session) -> str | None:
    latest = get_latest_platform_capital_reconciliation(db)
    if latest is None:
        return "platform_capital_reconciliation_missing"
    if not latest.ready or latest.delta_micro_usdc != 0:
        return "platform_capital_not_reconciled"

    settings = get_settings()
    if not is_reconciliation_fresh(
        latest,
        settings.platform_capital_reconciliation_max_age_seconds,
    ):
        return "platform_capital_reconciliation_stale"
    return None


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


def _public_event(event: PlatformCapitalEvent) -> PlatformCapitalEventPublic:
    return PlatformCapitalEventPublic(
        event_id=event.event_id,
        idempotency_key=event.idempotency_key,
        profit_month_id=event.profit_month_id,
        delta_micro_usdc=event.delta_micro_usdc,
        source=event.source,
        evidence_tx_hash=event.evidence_tx_hash,
        evidence_url=event.evidence_url,
        created_at=event.created_at,
    )


def _public_reconciliation(
    report: PlatformCapitalReconciliationReport,
) -> PlatformCapitalReconciliationReportPublic:
    return PlatformCapitalReconciliationReportPublic(
        funding_pool_address=report.funding_pool_address,
        ledger_balance_micro_usdc=report.ledger_balance_micro_usdc,
        onchain_balance_micro_usdc=report.onchain_balance_micro_usdc,
        delta_micro_usdc=report.delta_micro_usdc,
        ready=report.ready,
        blocked_reason=report.blocked_reason,
        computed_at=report.computed_at,
    )
