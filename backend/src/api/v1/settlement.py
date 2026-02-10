from __future__ import annotations

import re

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy.orm import Session

from src.core.database import get_db
from src.models.reconciliation_report import ReconciliationReport
from src.models.settlement import Settlement
from src.schemas.reconciliation import ReconciliationReportPublic
from src.schemas.settlement import (
    SettlementDetailData,
    SettlementDetailResponse,
    SettlementMonthSummary,
    SettlementMonthsData,
    SettlementMonthsResponse,
    SettlementPublic,
)

router = APIRouter(prefix="/api/v1/settlement", tags=["public-settlement", "settlement"])

_MONTH_RE = re.compile(r"^\d{6}$")


@router.get(
    "/{profit_month_id}",
    response_model=SettlementDetailResponse,
    summary="Get settlement status for month",
    description="Public read endpoint for settlement + reconciliation readiness.",
)
def get_settlement_status(
    profit_month_id: str,
    response: Response,
    db: Session = Depends(get_db),
) -> SettlementDetailResponse:
    _validate_month(profit_month_id)
    settlement = _latest_settlement(db, profit_month_id)
    reconciliation = _latest_reconciliation(db, profit_month_id)

    result = SettlementDetailResponse(
        success=True,
        data=SettlementDetailData(
            settlement=_settlement_public(settlement) if settlement else None,
            reconciliation=_reconciliation_public(reconciliation) if reconciliation else None,
            ready=bool(reconciliation.ready) if reconciliation else False,
        ),
    )
    etag_part = int(settlement.computed_at.timestamp()) if settlement else 0
    response.headers["Cache-Control"] = "public, max-age=30"
    response.headers["ETag"] = f'W/"settlement:{profit_month_id}:{etag_part}"'
    return result


@router.get(
    "/months",
    response_model=SettlementMonthsResponse,
    summary="List settlement months",
    description="Public read endpoint for settlement month index and readiness flags.",
)
def list_settlement_months(
    response: Response,
    limit: int = Query(24, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
) -> SettlementMonthsResponse:
    settlements = db.query(Settlement).order_by(Settlement.profit_month_id.desc(), Settlement.computed_at.desc(), Settlement.id.desc()).all()
    reconciliations = db.query(ReconciliationReport).order_by(ReconciliationReport.profit_month_id.desc(), ReconciliationReport.computed_at.desc(), ReconciliationReport.id.desc()).all()

    latest_settlement_by_month: dict[str, Settlement] = {}
    for row in settlements:
        latest_settlement_by_month.setdefault(row.profit_month_id, row)

    latest_reconciliation_by_month: dict[str, ReconciliationReport] = {}
    for row in reconciliations:
        latest_reconciliation_by_month.setdefault(row.profit_month_id, row)

    months = sorted(
        set(latest_settlement_by_month.keys()) | set(latest_reconciliation_by_month.keys()),
        reverse=True,
    )
    paged = months[offset : offset + limit]

    items: list[SettlementMonthSummary] = []
    for month in paged:
        settlement = latest_settlement_by_month.get(month)
        reconciliation = latest_reconciliation_by_month.get(month)
        items.append(
            SettlementMonthSummary(
                profit_month_id=month,
                revenue_sum_micro_usdc=settlement.revenue_sum_micro_usdc if settlement else 0,
                expense_sum_micro_usdc=settlement.expense_sum_micro_usdc if settlement else 0,
                profit_sum_micro_usdc=settlement.profit_sum_micro_usdc if settlement else 0,
                distributor_balance_micro_usdc=reconciliation.distributor_balance_micro_usdc if reconciliation else None,
                delta_micro_usdc=reconciliation.delta_micro_usdc if reconciliation else None,
                ready=bool(reconciliation.ready) if reconciliation else False,
                blocked_reason=reconciliation.blocked_reason if reconciliation else "missing_reconciliation",
                settlement_computed_at=settlement.computed_at if settlement else None,
                reconciliation_computed_at=reconciliation.computed_at if reconciliation else None,
            )
        )

    result = SettlementMonthsResponse(
        success=True,
        data=SettlementMonthsData(items=items, limit=limit, offset=offset, total=len(months)),
    )
    response.headers["Cache-Control"] = "public, max-age=30"
    response.headers["ETag"] = f'W/"settlement-months:{offset}:{limit}:{len(months)}"'
    return result


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


def _reconciliation_public(report: ReconciliationReport) -> ReconciliationReportPublic:
    return ReconciliationReportPublic(
        profit_month_id=report.profit_month_id,
        revenue_sum_micro_usdc=report.revenue_sum_micro_usdc,
        expense_sum_micro_usdc=report.expense_sum_micro_usdc,
        profit_sum_micro_usdc=report.profit_sum_micro_usdc,
        distributor_balance_micro_usdc=report.distributor_balance_micro_usdc,
        delta_micro_usdc=report.delta_micro_usdc,
        ready=report.ready,
        blocked_reason=report.blocked_reason,
        computed_at=report.computed_at,
    )


def _validate_month(profit_month_id: str) -> None:
    if not _MONTH_RE.fullmatch(profit_month_id):
        raise HTTPException(status_code=400, detail="profit_month_id must use YYYYMM format")
    month = int(profit_month_id[4:6])
    if month < 1 or month > 12:
        raise HTTPException(status_code=400, detail="profit_month_id month must be 01..12")
