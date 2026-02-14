from __future__ import annotations

import re

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy import func
from sqlalchemy.orm import Session

from src.core.config import get_settings
from src.core.database import get_db
from src.models.observed_usdc_transfer import ObservedUsdcTransfer
from src.schemas.stakers import StakerItem, StakersSummaryData, StakersSummaryResponse

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

