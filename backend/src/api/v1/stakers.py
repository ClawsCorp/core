from __future__ import annotations

import re
import secrets
from uuid import uuid4

from fastapi import APIRouter, Depends, Query, Request, Response
from sqlalchemy import case, desc, func
from sqlalchemy.orm import Session

from src.api.v1.dependencies import require_oracle_hmac
from src.core.audit import record_audit
from src.core.config import get_settings
from src.core.database import get_db
from src.models.observed_usdc_transfer import ObservedUsdcTransfer
from src.models.platform_capital_event import PlatformCapitalEvent
from src.models.platform_funding_deposit import PlatformFundingDeposit
from src.models.platform_funding_round import PlatformFundingRound
from src.models.reputation_event import ReputationEvent
from src.core.db_utils import insert_or_get_by_unique
from src.schemas.stakers import (
    PlatformFundingContributor,
    PlatformFundingRoundCloseRequest,
    PlatformFundingRoundCreateRequest,
    PlatformFundingRoundCreateResponse,
    PlatformFundingRoundPublic,
    PlatformFundingSummaryData,
    PlatformFundingSummaryResponse,
    PlatformFundingSyncData,
    PlatformFundingSyncResponse,
    PlatformInvestorReputationSyncData,
    PlatformInvestorReputationSyncResponse,
    StakerItem,
    StakersSummaryData,
    StakersSummaryResponse,
)
from src.services.reputation_hooks import emit_platform_investor_reputation_for_wallet

router = APIRouter(prefix="/api/v1", tags=["public-stakers"])

_ADDRESS_RE = re.compile(r"^0x[a-f0-9]{40}$")


def _resolve_funding_pool_address() -> tuple[str, str | None]:
    settings = get_settings()
    pool_addr = (settings.funding_pool_contract_address or "").strip().lower()
    if not pool_addr:
        return pool_addr, "funding_pool_address_missing"
    if not _ADDRESS_RE.fullmatch(pool_addr) or pool_addr == "0x0000000000000000000000000000000000000000":
        return pool_addr, "funding_pool_address_invalid"
    return pool_addr, None


def _platform_funding_round_public(row: PlatformFundingRound) -> PlatformFundingRoundPublic:
    return PlatformFundingRoundPublic(
        round_id=str(row.round_id),
        title=row.title,
        status=str(row.status),
        cap_micro_usdc=(int(row.cap_micro_usdc) if row.cap_micro_usdc is not None else None),
        opened_at=row.opened_at,
        closed_at=row.closed_at,
        created_at=row.created_at,
    )


@router.get(
    "/stakers",
    response_model=StakersSummaryResponse,
    summary="Platform stakers summary (FundingPool-based)",
    description="Public read endpoint: derives staker balances from observed USDC transfers into/out of FundingPool.",
)
def get_stakers_summary(
    response: Response,
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
) -> StakersSummaryResponse:
    pool_addr, blocked_reason = _resolve_funding_pool_address()

    if blocked_reason is not None:
        response.headers["Cache-Control"] = "public, max-age=30"
        return StakersSummaryResponse(
            success=False,
            data=StakersSummaryData(
                funding_pool_address=pool_addr or None,
                stakers_count=0,
                total_staked_micro_usdc=0,
                top=[],
                blocked_reason=blocked_reason,
            ),
        )

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

    if any(int(v) < 0 for v in net_by_address.values()):
        response.headers["Cache-Control"] = "public, max-age=30"
        return StakersSummaryResponse(
            success=False,
            data=StakersSummaryData(
                funding_pool_address=pool_addr,
                stakers_count=0,
                total_staked_micro_usdc=0,
                top=[],
                blocked_reason="stakers_negative_balance",
            ),
        )

    items = [(a, int(v)) for a, v in net_by_address.items() if int(v) > 0]
    items = sorted(items, key=lambda kv: (-int(kv[1]), kv[0]))
    total = sum(v for _a, v in items)

    top = [StakerItem(address=a, stake_micro_usdc=v) for a, v in items[: int(limit)]]

    response.headers["Cache-Control"] = "public, max-age=30"
    return StakersSummaryResponse(
        success=True,
        data=StakersSummaryData(
            funding_pool_address=pool_addr,
            stakers_count=len(items),
            total_staked_micro_usdc=total,
            top=top,
            blocked_reason=None,
        ),
    )


@router.get(
    "/platform/funding",
    response_model=PlatformFundingSummaryResponse,
    summary="Get platform funding summary (FundingPool rounds and cap table)",
)
def get_platform_funding_summary(
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
) -> PlatformFundingSummaryResponse:
    pool_addr, blocked_reason = _resolve_funding_pool_address()

    open_round = (
        db.query(PlatformFundingRound)
        .filter(PlatformFundingRound.status == "open")
        .order_by(PlatformFundingRound.opened_at.desc(), PlatformFundingRound.id.desc())
        .first()
    )

    open_round_raised_observed = 0
    if open_round is not None:
        open_round_raised_observed = int(
            db.query(func.coalesce(func.sum(PlatformFundingDeposit.amount_micro_usdc), 0))
            .filter(PlatformFundingDeposit.funding_round_id == int(open_round.id))
            .scalar()
            or 0
        )

    total_raised_observed = int(
        db.query(func.coalesce(func.sum(PlatformFundingDeposit.amount_micro_usdc), 0)).scalar() or 0
    )

    inflow_case = case((PlatformCapitalEvent.delta_micro_usdc > 0, PlatformCapitalEvent.delta_micro_usdc), else_=0)
    total_inflow_ledger = int(db.query(func.coalesce(func.sum(inflow_case), 0)).scalar() or 0)

    open_round_inflow_ledger = 0
    if open_round is not None:
        open_round_inflow_query = db.query(func.coalesce(func.sum(inflow_case), 0)).filter(
            PlatformCapitalEvent.created_at >= open_round.opened_at,
        )
        if open_round.closed_at is not None:
            open_round_inflow_query = open_round_inflow_query.filter(PlatformCapitalEvent.created_at <= open_round.closed_at)
        open_round_inflow_ledger = int(open_round_inflow_query.scalar() or 0)

    contributors_rows = (
        db.query(
            PlatformFundingDeposit.from_address,
            func.coalesce(func.sum(PlatformFundingDeposit.amount_micro_usdc), 0).label("amount_micro_usdc"),
        )
        .filter(PlatformFundingDeposit.funding_round_id == (open_round.id if open_round is not None else None))
        .group_by(PlatformFundingDeposit.from_address)
        .order_by(desc("amount_micro_usdc"), PlatformFundingDeposit.from_address.asc())
        .limit(int(limit))
        .all()
        if open_round is not None
        else []
    )
    contributors = [
        PlatformFundingContributor(address=str(addr), amount_micro_usdc=int(amount or 0))
        for addr, amount in contributors_rows
    ]

    contributors_total_count = 0
    if open_round is not None:
        contributors_total_count = int(
            db.query(func.count(func.distinct(PlatformFundingDeposit.from_address)))
            .filter(PlatformFundingDeposit.funding_round_id == int(open_round.id))
            .scalar()
            or 0
        )

    total_raised = total_raised_observed
    open_round_raised = open_round_raised_observed
    contributors_data_source = "observed_transfers"
    unattributed_micro_usdc = 0
    if total_inflow_ledger > total_raised_observed:
        total_raised = total_inflow_ledger
        if open_round is not None:
            open_round_raised = max(open_round_raised_observed, open_round_inflow_ledger, total_inflow_ledger)
        else:
            open_round_raised = max(open_round_raised_observed, open_round_inflow_ledger)
        contributors_data_source = "mixed_with_ledger_fallback" if total_raised_observed > 0 else "ledger_fallback"
        unattributed_micro_usdc = int(total_inflow_ledger - total_raised_observed)

    last_deposit_at = db.query(func.max(PlatformFundingDeposit.observed_at)).scalar()

    return PlatformFundingSummaryResponse(
        success=True,
        data=PlatformFundingSummaryData(
            funding_pool_address=pool_addr or None,
            open_round=_platform_funding_round_public(open_round) if open_round is not None else None,
            open_round_raised_micro_usdc=int(open_round_raised),
            total_raised_micro_usdc=int(total_raised),
            contributors=contributors,
            contributors_total_count=int(contributors_total_count),
            contributors_data_source=contributors_data_source,
            unattributed_micro_usdc=int(unattributed_micro_usdc),
            last_deposit_at=last_deposit_at,
            blocked_reason=blocked_reason,
        ),
    )


@router.post(
    "/oracle/platform/funding-rounds",
    response_model=PlatformFundingRoundCreateResponse,
    tags=["oracle-platform-funding"],
)
async def open_platform_funding_round(
    payload: PlatformFundingRoundCreateRequest,
    request: Request,
    _: str = Depends(require_oracle_hmac),
    db: Session = Depends(get_db),
) -> PlatformFundingRoundCreateResponse:
    pool_addr, blocked_reason = _resolve_funding_pool_address()
    request_id = request.headers.get("X-Request-Id") or request.headers.get("X-Request-ID") or str(uuid4())
    body_hash = getattr(request.state, "body_hash", "")
    if blocked_reason is not None:
        _record_oracle_audit(request, db, body_hash, request_id, payload.idempotency_key, commit=True)
        return PlatformFundingRoundCreateResponse(success=False, data=None, blocked_reason=blocked_reason)

    existing_open = (
        db.query(PlatformFundingRound)
        .filter(PlatformFundingRound.status == "open")
        .order_by(PlatformFundingRound.opened_at.desc(), PlatformFundingRound.id.desc())
        .first()
    )
    if existing_open is not None and str(existing_open.idempotency_key) != str(payload.idempotency_key):
        _record_oracle_audit(request, db, body_hash, request_id, payload.idempotency_key, commit=True)
        return PlatformFundingRoundCreateResponse(success=False, data=None, blocked_reason="funding_round_already_open")

    row = PlatformFundingRound(
        round_id=f"pfr_{secrets.token_hex(8)}",
        idempotency_key=payload.idempotency_key,
        title=payload.title,
        status="open",
        cap_micro_usdc=int(payload.cap_micro_usdc) if payload.cap_micro_usdc is not None else None,
    )
    row, _ = insert_or_get_by_unique(
        db,
        instance=row,
        model=PlatformFundingRound,
        unique_filter={"idempotency_key": payload.idempotency_key},
    )
    _record_oracle_audit(request, db, body_hash, request_id, payload.idempotency_key, commit=False)
    db.commit()
    db.refresh(row)
    return PlatformFundingRoundCreateResponse(
        success=True,
        data=_platform_funding_round_public(row),
        blocked_reason=None,
    )


@router.post(
    "/oracle/platform/funding-rounds/{round_id}/close",
    response_model=PlatformFundingRoundCreateResponse,
    tags=["oracle-platform-funding"],
)
async def close_platform_funding_round(
    round_id: str,
    payload: PlatformFundingRoundCloseRequest,
    request: Request,
    _: str = Depends(require_oracle_hmac),
    db: Session = Depends(get_db),
) -> PlatformFundingRoundCreateResponse:
    row = db.query(PlatformFundingRound).filter(PlatformFundingRound.round_id == round_id).first()
    if row is None:
        return PlatformFundingRoundCreateResponse(success=False, data=None, blocked_reason="funding_round_not_found")

    request_id = request.headers.get("X-Request-Id") or request.headers.get("X-Request-ID") or str(uuid4())
    body_hash = getattr(request.state, "body_hash", "")

    if row.status != "closed":
        row.status = "closed"
        row.closed_at = func.now()
        db.add(row)

    _record_oracle_audit(request, db, body_hash, request_id, payload.idempotency_key, commit=False)
    db.commit()
    db.refresh(row)
    return PlatformFundingRoundCreateResponse(success=True, data=_platform_funding_round_public(row), blocked_reason=None)


@router.post(
    "/oracle/platform-funding/sync",
    response_model=PlatformFundingSyncResponse,
    tags=["oracle-platform-funding"],
)
async def sync_platform_funding_deposits(
    request: Request,
    _: str = Depends(require_oracle_hmac),
    db: Session = Depends(get_db),
) -> PlatformFundingSyncResponse:
    pool_addr, blocked_reason = _resolve_funding_pool_address()
    request_id = request.headers.get("X-Request-Id") or request.headers.get("X-Request-ID") or str(uuid4())
    body_hash = getattr(request.state, "body_hash", "")
    sync_idem = request.headers.get("Idempotency-Key") or f"platform_funding_sync:{request_id}"

    if blocked_reason is not None:
        _record_oracle_audit(request, db, body_hash, request_id, sync_idem, commit=True)
        return PlatformFundingSyncResponse(success=False, data=None, blocked_reason=blocked_reason)

    open_round = (
        db.query(PlatformFundingRound)
        .filter(PlatformFundingRound.status == "open")
        .order_by(PlatformFundingRound.opened_at.desc(), PlatformFundingRound.id.desc())
        .first()
    )

    transfers = (
        db.query(ObservedUsdcTransfer)
        .filter(ObservedUsdcTransfer.to_address == pool_addr, ObservedUsdcTransfer.from_address != pool_addr)
        .order_by(ObservedUsdcTransfer.block_number.desc(), ObservedUsdcTransfer.log_index.desc())
        .limit(1000)
        .all()
    )

    inserted = 0
    before_rep_count = int(
        db.query(func.count(ReputationEvent.id))
        .filter(ReputationEvent.source == "platform_capital_contributed")
        .scalar()
        or 0
    )
    recognized = 0
    for transfer in transfers:
        row = PlatformFundingDeposit(
            deposit_id=f"pfdp_{secrets.token_hex(8)}",
            funding_round_id=(int(open_round.id) if open_round is not None else None),
            observed_transfer_id=int(transfer.id),
            chain_id=int(transfer.chain_id),
            from_address=str(transfer.from_address).lower(),
            to_address=str(transfer.to_address).lower(),
            amount_micro_usdc=int(transfer.amount_micro_usdc),
            block_number=int(transfer.block_number),
            tx_hash=str(transfer.tx_hash).lower(),
            log_index=int(transfer.log_index),
            observed_at=transfer.observed_at,
        )
        _, created = insert_or_get_by_unique(
            db,
            instance=row,
            model=PlatformFundingDeposit,
            unique_filter={"observed_transfer_id": int(transfer.id)},
        )
        if created:
            inserted += 1
        previous_rep_count = int(
            db.query(func.count(ReputationEvent.id))
            .filter(
                ReputationEvent.source == "platform_capital_contributed",
                ReputationEvent.idempotency_key
                == (
                    f"rep:platform_capital_contributed:{int(transfer.chain_id)}:"
                    f"{str(transfer.tx_hash).lower()}:{int(transfer.log_index)}"
                ),
            )
            .scalar()
            or 0
        )
        emit_platform_investor_reputation_for_wallet(
            db,
            wallet_address=str(transfer.from_address).lower(),
            amount_micro_usdc=int(transfer.amount_micro_usdc),
            chain_id=int(transfer.chain_id),
            tx_hash=str(transfer.tx_hash).lower(),
            log_index=int(transfer.log_index),
        )
        current_rep_count = int(
            db.query(func.count(ReputationEvent.id))
            .filter(
                ReputationEvent.source == "platform_capital_contributed",
                ReputationEvent.idempotency_key
                == (
                    f"rep:platform_capital_contributed:{int(transfer.chain_id)}:"
                    f"{str(transfer.tx_hash).lower()}:{int(transfer.log_index)}"
                ),
            )
            .scalar()
            or 0
        )
        if current_rep_count > previous_rep_count:
            recognized += 1

    after_rep_count = int(
        db.query(func.count(ReputationEvent.id))
        .filter(ReputationEvent.source == "platform_capital_contributed")
        .scalar()
        or 0
    )
    _record_oracle_audit(request, db, body_hash, request_id, sync_idem, commit=False)
    db.commit()
    return PlatformFundingSyncResponse(
        success=True,
        data=PlatformFundingSyncData(
            funding_pool_address=pool_addr,
            transfers_seen=len(transfers),
            deposits_inserted=int(inserted),
            reputation_events_created=max(after_rep_count - before_rep_count, 0),
            recognized_investor_transfers=int(recognized),
            open_round_id=(str(open_round.round_id) if open_round is not None else None),
        ),
        blocked_reason=None,
    )


@router.post(
    "/oracle/platform-capital/reputation-sync",
    response_model=PlatformInvestorReputationSyncResponse,
    tags=["oracle-reputation"],
)
async def sync_platform_investor_reputation(
    request: Request,
    _: str = Depends(require_oracle_hmac),
    db: Session = Depends(get_db),
) -> PlatformInvestorReputationSyncResponse:
    pool_addr, blocked_reason = _resolve_funding_pool_address()
    request_id = request.headers.get("X-Request-Id") or request.headers.get("X-Request-ID") or str(uuid4())
    body_hash = getattr(request.state, "body_hash", "")
    idempotency_key = request.headers.get("Idempotency-Key") or f"platform_capital_reputation_sync:{request_id}"

    if blocked_reason is not None:
        _record_oracle_audit(request, db, body_hash, request_id, idempotency_key, commit=True)
        return PlatformInvestorReputationSyncResponse(success=False, data=None, blocked_reason=blocked_reason)

    transfers = (
        db.query(ObservedUsdcTransfer)
        .filter(ObservedUsdcTransfer.to_address == pool_addr, ObservedUsdcTransfer.from_address != pool_addr)
        .order_by(ObservedUsdcTransfer.block_number.desc(), ObservedUsdcTransfer.log_index.desc())
        .limit(1000)
        .all()
    )

    before_count = int(
        db.query(func.count(ReputationEvent.id))
        .filter(ReputationEvent.source == "platform_capital_contributed")
        .scalar()
        or 0
    )
    recognized = 0
    for transfer in transfers:
        previous_count = int(
            db.query(func.count(ReputationEvent.id))
            .filter(
                ReputationEvent.source == "platform_capital_contributed",
                ReputationEvent.idempotency_key
                == f"rep:platform_capital_contributed:{int(transfer.chain_id)}:{str(transfer.tx_hash).lower()}:{int(transfer.log_index)}",
            )
            .scalar()
            or 0
        )
        emit_platform_investor_reputation_for_wallet(
            db,
            wallet_address=str(transfer.from_address).lower(),
            amount_micro_usdc=int(transfer.amount_micro_usdc),
            chain_id=int(transfer.chain_id),
            tx_hash=str(transfer.tx_hash).lower(),
            log_index=int(transfer.log_index),
        )
        current_count = int(
            db.query(func.count(ReputationEvent.id))
            .filter(
                ReputationEvent.source == "platform_capital_contributed",
                ReputationEvent.idempotency_key
                == f"rep:platform_capital_contributed:{int(transfer.chain_id)}:{str(transfer.tx_hash).lower()}:{int(transfer.log_index)}",
            )
            .scalar()
            or 0
        )
        if current_count > previous_count:
            recognized += 1

    after_count = int(
        db.query(func.count(ReputationEvent.id))
        .filter(ReputationEvent.source == "platform_capital_contributed")
        .scalar()
        or 0
    )

    _record_oracle_audit(request, db, body_hash, request_id, idempotency_key, commit=False)
    db.commit()
    return PlatformInvestorReputationSyncResponse(
        success=True,
        data=PlatformInvestorReputationSyncData(
            funding_pool_address=pool_addr,
            transfers_seen=len(transfers),
            reputation_events_created=max(after_count - before_count, 0),
            recognized_investor_transfers=recognized,
        ),
        blocked_reason=None,
    )


def _record_oracle_audit(
    request: Request,
    db: Session,
    body_hash: str,
    request_id: str,
    idempotency_key: str,
    *,
    commit: bool,
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
