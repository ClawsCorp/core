from __future__ import annotations

import re
from uuid import uuid4

from fastapi import APIRouter, Depends, Query, Request, Response
from sqlalchemy import func
from sqlalchemy.orm import Session

from src.api.v1.dependencies import require_oracle_hmac
from src.core.audit import record_audit
from src.core.config import get_settings
from src.core.database import get_db
from src.models.observed_usdc_transfer import ObservedUsdcTransfer
from src.models.reputation_event import ReputationEvent
from src.schemas.stakers import (
    PlatformInvestorReputationSyncData,
    PlatformInvestorReputationSyncResponse,
    StakerItem,
    StakersSummaryData,
    StakersSummaryResponse,
)
from src.services.reputation_hooks import emit_platform_investor_reputation_for_wallet

router = APIRouter(prefix="/api/v1", tags=["public-stakers"])

_ADDRESS_RE = re.compile(r"^0x[a-f0-9]{40}$")


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
    settings = get_settings()
    pool_addr = (settings.funding_pool_contract_address or "").strip().lower()

    blocked_reason: str | None = None
    if not pool_addr:
        blocked_reason = "funding_pool_address_missing"
    elif not _ADDRESS_RE.fullmatch(pool_addr) or pool_addr == "0x0000000000000000000000000000000000000000":
        blocked_reason = "funding_pool_address_invalid"

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
    settings = get_settings()
    pool_addr = (settings.funding_pool_contract_address or "").strip().lower()
    request_id = request.headers.get("X-Request-Id") or request.headers.get("X-Request-ID") or str(uuid4())
    body_hash = getattr(request.state, "body_hash", "")
    idempotency_key = request.headers.get("Idempotency-Key") or f"platform_capital_reputation_sync:{request_id}"

    blocked_reason: str | None = None
    if not pool_addr:
        blocked_reason = "funding_pool_address_missing"
    elif not _ADDRESS_RE.fullmatch(pool_addr) or pool_addr == "0x0000000000000000000000000000000000000000":
        blocked_reason = "funding_pool_address_invalid"
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
