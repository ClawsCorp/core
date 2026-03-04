from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel
from sqlalchemy.orm import Session

from src.core.config import get_settings
from src.core.database import get_db
from src.models.agent import Agent
from src.models.indexer_cursor import IndexerCursor
from src.services.platform_capital import (
    get_latest_platform_capital_reconciliation,
    get_platform_capital_balance_micro_usdc,
    get_platform_capital_spendable_balance_micro_usdc,
)

router = APIRouter(prefix="/api/v1", tags=["public-system"])


class StatsData(BaseModel):
    app_version: str
    default_chain_id: int
    total_registered_agents: int
    server_time_utc: str
    project_capital_reconciliation_max_age_seconds: int
    platform_capital_reconciliation_max_age_seconds: int
    project_revenue_reconciliation_max_age_seconds: int
    platform_capital_ledger_balance_micro_usdc: int
    platform_capital_spendable_balance_micro_usdc: int
    platform_capital_reconciliation_ready: bool | None
    platform_capital_reconciliation_delta_micro_usdc: int | None
    platform_capital_reconciliation_computed_at: str | None


class IndexerStatusData(BaseModel):
    cursor_key: str
    chain_id: int | None
    last_block_number: int | None
    updated_at: str | None
    age_seconds: int | None
    max_age_seconds: int
    stale: bool
    lookback_blocks_configured: int
    min_lookback_blocks_configured: int
    last_scan_window_blocks: int | None
    degraded: bool
    degraded_since: str | None
    degraded_age_seconds: int | None
    degraded_max_age_seconds: int
    last_error_hint: str | None


class IndexerStatusResponse(BaseModel):
    success: bool
    data: IndexerStatusData


class StatsResponse(BaseModel):
    success: bool
    data: StatsData


@router.get(
    "/stats",
    response_model=StatsResponse,
    summary="Public platform stats",
    description="Portal-safe aggregate platform counters.",
)
def get_stats(response: Response, db: Session = Depends(get_db)) -> StatsResponse:
    settings = get_settings()
    total_agents = db.query(Agent).count()
    # Cache for 30s; round the displayed server time to the same bucket so ETag matches payload.
    now = datetime.now(timezone.utc)
    time_bucket_seconds = 30
    bucketed_timestamp = int(now.timestamp() // time_bucket_seconds) * time_bucket_seconds
    bucketed_time = datetime.fromtimestamp(bucketed_timestamp, tz=timezone.utc)
    latest_platform_reconciliation = get_latest_platform_capital_reconciliation(db)
    platform_capital_ledger_balance = get_platform_capital_balance_micro_usdc(db)
    platform_capital_spendable_balance = get_platform_capital_spendable_balance_micro_usdc(db)

    result = StatsResponse(
        success=True,
        data=StatsData(
            app_version=settings.app_version,
            default_chain_id=int(settings.default_chain_id),
            total_registered_agents=total_agents,
            server_time_utc=bucketed_time.isoformat(),
            project_capital_reconciliation_max_age_seconds=settings.project_capital_reconciliation_max_age_seconds,
            platform_capital_reconciliation_max_age_seconds=settings.platform_capital_reconciliation_max_age_seconds,
            project_revenue_reconciliation_max_age_seconds=settings.project_revenue_reconciliation_max_age_seconds,
            platform_capital_ledger_balance_micro_usdc=platform_capital_ledger_balance,
            platform_capital_spendable_balance_micro_usdc=platform_capital_spendable_balance,
            platform_capital_reconciliation_ready=(
                bool(latest_platform_reconciliation.ready) if latest_platform_reconciliation is not None else None
            ),
            platform_capital_reconciliation_delta_micro_usdc=(
                int(latest_platform_reconciliation.delta_micro_usdc)
                if latest_platform_reconciliation is not None and latest_platform_reconciliation.delta_micro_usdc is not None
                else None
            ),
            platform_capital_reconciliation_computed_at=(
                latest_platform_reconciliation.computed_at.isoformat()
                if latest_platform_reconciliation is not None
                else None
            ),
        ),
    )
    etag_seed = (
        f"{result.data.app_version}:"
        f"{result.data.default_chain_id}:"
        f"{result.data.total_registered_agents}:"
        f"{bucketed_timestamp}:"
        f"{result.data.project_capital_reconciliation_max_age_seconds}:"
        f"{result.data.platform_capital_reconciliation_max_age_seconds}:"
        f"{result.data.project_revenue_reconciliation_max_age_seconds}"
        f":{result.data.platform_capital_ledger_balance_micro_usdc}"
        f":{result.data.platform_capital_spendable_balance_micro_usdc}"
        f":{result.data.platform_capital_reconciliation_ready}"
        f":{result.data.platform_capital_reconciliation_delta_micro_usdc}"
        f":{result.data.platform_capital_reconciliation_computed_at or ''}"
    )
    response.headers["Cache-Control"] = "public, max-age=30"
    response.headers["ETag"] = f'W/"{etag_seed}"'
    return result


@router.get(
    "/indexer/status",
    response_model=IndexerStatusResponse,
    summary="Public indexer runtime status",
    description="Portal-safe runtime status for the USDC transfer indexer, including adaptive lookback degradation.",
)
def get_indexer_status(response: Response, db: Session = Depends(get_db)) -> IndexerStatusResponse:
    settings = get_settings()
    now = datetime.now(timezone.utc)
    cursor = (
        db.query(IndexerCursor)
        .filter(IndexerCursor.cursor_key == "usdc_transfers")
        .order_by(IndexerCursor.updated_at.desc(), IndexerCursor.id.desc())
        .first()
    )
    lookback_blocks_configured = max(1, int(settings.indexer_lookback_blocks or 500))
    min_lookback_blocks_configured = max(1, int(settings.indexer_min_lookback_blocks or 5))
    if cursor is None:
        data = IndexerStatusData(
            cursor_key="usdc_transfers",
            chain_id=None,
            last_block_number=None,
            updated_at=None,
            age_seconds=None,
            max_age_seconds=int(settings.indexer_cursor_max_age_seconds),
            stale=True,
            lookback_blocks_configured=lookback_blocks_configured,
            min_lookback_blocks_configured=min_lookback_blocks_configured,
            last_scan_window_blocks=None,
            degraded=False,
            degraded_since=None,
            degraded_age_seconds=None,
            degraded_max_age_seconds=int(settings.indexer_degraded_max_age_seconds),
            last_error_hint=None,
        )
        response.headers["Cache-Control"] = "no-store"
        return IndexerStatusResponse(success=True, data=data)

    updated_at = cursor.updated_at if cursor.updated_at.tzinfo else cursor.updated_at.replace(tzinfo=timezone.utc)
    age_seconds = int((now - updated_at).total_seconds())
    degraded_since = None
    degraded_age_seconds = None
    if cursor.degraded_since is not None:
        degraded_since = (
            cursor.degraded_since if cursor.degraded_since.tzinfo else cursor.degraded_since.replace(tzinfo=timezone.utc)
        )
        degraded_age_seconds = int((now - degraded_since).total_seconds())
    last_scan_window_blocks = int(cursor.last_scan_window_blocks) if cursor.last_scan_window_blocks is not None else None
    data = IndexerStatusData(
        cursor_key=cursor.cursor_key,
        chain_id=int(cursor.chain_id),
        last_block_number=int(cursor.last_block_number),
        updated_at=updated_at.isoformat(),
        age_seconds=age_seconds,
        max_age_seconds=int(settings.indexer_cursor_max_age_seconds),
        stale=age_seconds > int(settings.indexer_cursor_max_age_seconds),
        lookback_blocks_configured=lookback_blocks_configured,
        min_lookback_blocks_configured=min_lookback_blocks_configured,
        last_scan_window_blocks=last_scan_window_blocks,
        degraded=bool(last_scan_window_blocks is not None and last_scan_window_blocks < lookback_blocks_configured),
        degraded_since=degraded_since.isoformat() if degraded_since is not None else None,
        degraded_age_seconds=degraded_age_seconds,
        degraded_max_age_seconds=int(settings.indexer_degraded_max_age_seconds),
        last_error_hint=cursor.last_error_hint,
    )
    response.headers["Cache-Control"] = "no-store"
    return IndexerStatusResponse(success=True, data=data)
