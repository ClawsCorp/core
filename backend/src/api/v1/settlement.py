from __future__ import annotations

import re
import hashlib

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy.orm import Session

from src.core.database import get_db
from src.models.dividend_payout import DividendPayout
from src.models.project import Project
from src.models.project_settlement import ProjectSettlement
from src.models.reconciliation_report import ReconciliationReport
from src.models.settlement import Settlement
from src.schemas.project_settlement import ProjectSettlementPublic
from src.schemas.reconciliation import ReconciliationReportPublic
from src.schemas.settlement import (
    SettlementDetailData,
    SettlementDetailResponse,
    SettlementMonthSummary,
    SettlementMonthsData,
    SettlementMonthsResponse,
    SettlementPayoutPublic,
    SettlementPublic,
)
from src.schemas.settlement_consolidated import (
    ConsolidatedSettlementData,
    ConsolidatedSettlementProjectsSums,
    ConsolidatedSettlementResponse,
)

router = APIRouter(prefix="/api/v1/settlement", tags=["public-settlement", "settlement"])

_MONTH_RE = re.compile(r"^\d{6}$")


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
    payouts = db.query(DividendPayout).order_by(DividendPayout.profit_month_id.desc(), DividendPayout.payout_executed_at.desc(), DividendPayout.id.desc()).all()

    latest_settlement_by_month: dict[str, Settlement] = {}
    for row in settlements:
        latest_settlement_by_month.setdefault(row.profit_month_id, row)

    latest_reconciliation_by_month: dict[str, ReconciliationReport] = {}
    for row in reconciliations:
        latest_reconciliation_by_month.setdefault(row.profit_month_id, row)

    latest_payout_by_month: dict[str, DividendPayout] = {}
    for row in payouts:
        latest_payout_by_month.setdefault(row.profit_month_id, row)

    months = sorted(
        set(latest_settlement_by_month.keys())
        | set(latest_reconciliation_by_month.keys())
        | set(latest_payout_by_month.keys()),
        reverse=True,
    )
    paged = months[offset : offset + limit]

    items: list[SettlementMonthSummary] = []
    for month in paged:
        settlement = latest_settlement_by_month.get(month)
        reconciliation = latest_reconciliation_by_month.get(month)
        payout = latest_payout_by_month.get(month)
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
                payout_tx_hash=payout.tx_hash if payout else None,
                payout_executed_at=payout.payout_executed_at if payout else None,
                payout_status=payout.status if payout else None,
            )
        )

    result = SettlementMonthsResponse(
        success=True,
        data=SettlementMonthsData(items=items, limit=limit, offset=offset, total=len(months)),
    )
    # ETag should reflect the actual page contents (not just the total).
    etag_payload = "|".join(
        [
            f"{i.profit_month_id}:{i.ready}:{i.delta_micro_usdc}:{i.payout_status}:{i.payout_tx_hash}:{i.settlement_computed_at}:{i.reconciliation_computed_at}:{i.payout_executed_at}"
            for i in items
        ]
    ).encode("utf-8", errors="replace")
    etag_hash = hashlib.sha256(etag_payload).hexdigest()[:16]
    response.headers["Cache-Control"] = "public, max-age=30"
    response.headers["ETag"] = f'W/"settlement-months:{offset}:{limit}:{len(months)}:{etag_hash}"'
    return result


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
    payout = _latest_payout(db, profit_month_id)

    result = SettlementDetailResponse(
        success=True,
        data=SettlementDetailData(
            settlement=_settlement_public(settlement) if settlement else None,
            reconciliation=_reconciliation_public(reconciliation) if reconciliation else None,
            payout=_payout_public(payout) if payout else None,
            ready=bool(reconciliation.ready) if reconciliation else False,
        ),
    )
    settlement_ts = int(settlement.computed_at.timestamp()) if settlement else 0
    reconciliation_ts = int(reconciliation.computed_at.timestamp()) if reconciliation else 0
    payout_ts = int(payout.created_at.timestamp()) if payout else 0
    # Include key fields that can change without settlement recompute.
    payout_part = f"{getattr(payout, 'status', None)}:{getattr(payout, 'tx_hash', None)}"
    recon_part = f"{getattr(reconciliation, 'ready', None)}:{getattr(reconciliation, 'delta_micro_usdc', None)}"
    etag_seed = f"{profit_month_id}:{max(settlement_ts, reconciliation_ts, payout_ts)}:{payout_part}:{recon_part}"
    response.headers["Cache-Control"] = "public, max-age=30"
    response.headers["ETag"] = f'W/"settlement:{etag_seed}"'
    return result


@router.get(
    "/{profit_month_id}/consolidated",
    response_model=ConsolidatedSettlementResponse,
    summary="Get consolidated settlement view for month",
    description="Public read endpoint: platform settlement status plus latest per-project settlement rows for the same month.",
)
def get_consolidated_settlement_status(
    profit_month_id: str,
    response: Response,
    db: Session = Depends(get_db),
) -> ConsolidatedSettlementResponse:
    _validate_month(profit_month_id)

    # Platform month status (same primitives as /api/v1/settlement/{YYYYMM}).
    settlement = _latest_settlement(db, profit_month_id)
    reconciliation = _latest_reconciliation(db, profit_month_id)
    payout = _latest_payout(db, profit_month_id)
    platform = SettlementDetailData(
        settlement=_settlement_public(settlement) if settlement else None,
        reconciliation=_reconciliation_public(reconciliation) if reconciliation else None,
        payout=_payout_public(payout) if payout else None,
        ready=bool(reconciliation.ready) if reconciliation else False,
    )

    # Latest per-project settlement rows for the month.
    rows = (
        db.query(ProjectSettlement)
        .filter(ProjectSettlement.profit_month_id == profit_month_id)
        .order_by(ProjectSettlement.computed_at.desc(), ProjectSettlement.id.desc())
        .all()
    )
    latest_by_project_pk: dict[int, ProjectSettlement] = {}
    for row in rows:
        latest_by_project_pk.setdefault(row.project_id, row)

    projects = db.query(Project).order_by(Project.project_id.asc()).all()
    public_projects: list[ProjectSettlementPublic] = []
    revenue_sum = 0
    expense_sum = 0
    profit_sum = 0
    for project in projects:
        s = latest_by_project_pk.get(project.id)
        if s is None:
            continue
        revenue_sum += int(s.revenue_sum_micro_usdc)
        expense_sum += int(s.expense_sum_micro_usdc)
        profit_sum += int(s.profit_sum_micro_usdc)
        public_projects.append(
            ProjectSettlementPublic(
                project_id=project.project_id,
                profit_month_id=s.profit_month_id,
                revenue_sum_micro_usdc=int(s.revenue_sum_micro_usdc),
                expense_sum_micro_usdc=int(s.expense_sum_micro_usdc),
                profit_sum_micro_usdc=int(s.profit_sum_micro_usdc),
                profit_nonnegative=bool(s.profit_nonnegative),
                note=s.note,
                computed_at=s.computed_at,
            )
        )

    result = ConsolidatedSettlementResponse(
        success=True,
        data=ConsolidatedSettlementData(
            profit_month_id=profit_month_id,
            platform=platform,
            projects=public_projects,
            sums=ConsolidatedSettlementProjectsSums(
                projects_revenue_sum_micro_usdc=revenue_sum,
                projects_expense_sum_micro_usdc=expense_sum,
                projects_profit_sum_micro_usdc=profit_sum,
                projects_with_settlement_count=len(public_projects),
            ),
        ),
    )

    # Coarse ETag: reflect platform (settlement/recon/payout) + latest project settlement timestamps.
    settlement_ts = int(settlement.computed_at.timestamp()) if settlement else 0
    reconciliation_ts = int(reconciliation.computed_at.timestamp()) if reconciliation else 0
    payout_ts = int(payout.created_at.timestamp()) if payout else 0
    projects_ts = max([int(p.computed_at.timestamp()) for p in public_projects], default=0)
    response.headers["Cache-Control"] = "public, max-age=30"
    response.headers["ETag"] = f'W/"settlement-consolidated:{profit_month_id}:{max(settlement_ts, reconciliation_ts, payout_ts, projects_ts)}:{len(public_projects)}"'
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


def _latest_payout(db: Session, profit_month_id: str) -> DividendPayout | None:
    return (
        db.query(DividendPayout)
        .filter(DividendPayout.profit_month_id == profit_month_id)
        .order_by(DividendPayout.created_at.desc(), DividendPayout.id.desc())
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


def _payout_public(payout: DividendPayout) -> SettlementPayoutPublic:
    return SettlementPayoutPublic(
        tx_hash=payout.tx_hash,
        executed_at=payout.payout_executed_at,
        idempotency_key=payout.idempotency_key,
        status=payout.status,
        confirmed_at=payout.confirmed_at,
        failed_at=payout.failed_at,
        block_number=payout.block_number,
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
