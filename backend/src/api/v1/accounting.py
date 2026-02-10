from __future__ import annotations

import re

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from src.core.database import get_db
from src.models.expense_event import ExpenseEvent
from src.models.project import Project
from src.models.revenue_event import RevenueEvent
from src.schemas.accounting import AccountingMonthSummary, AccountingMonthsData, AccountingMonthsResponse

router = APIRouter(prefix="/api/v1/accounting", tags=["accounting"])

_MONTH_RE = re.compile(r"^\d{6}$")


@router.get("/months", response_model=AccountingMonthsResponse)
def list_monthly_profit(
    profit_month_id: str | None = Query(None),
    project_id: str | None = Query(None),
    limit: int = Query(24, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
) -> AccountingMonthsResponse:
    if profit_month_id is not None:
        _validate_month(profit_month_id)

    internal_project_id: int | None = None
    if project_id is not None:
        project = db.query(Project).filter(Project.project_id == project_id).first()
        if project is None:
            raise HTTPException(status_code=404, detail="Project not found")
        internal_project_id = project.id

    revenue_rows = (
        _revenue_grouped(db, profit_month_id, internal_project_id)
    )
    expense_rows = (
        _expense_grouped(db, profit_month_id, internal_project_id)
    )

    revenue_by_month = {row[0]: int(row[1] or 0) for row in revenue_rows}
    expense_by_month = {row[0]: int(row[1] or 0) for row in expense_rows}

    if profit_month_id is not None:
        months = [profit_month_id]
    else:
        months = sorted(set(revenue_by_month) | set(expense_by_month), reverse=True)

    total = len(months)
    paged_months = months[offset : offset + limit]
    items = [
        _summary_item(
            month,
            revenue_by_month.get(month, 0),
            expense_by_month.get(month, 0),
        )
        for month in paged_months
    ]

    return AccountingMonthsResponse(
        success=True,
        data=AccountingMonthsData(items=items, limit=limit, offset=offset, total=total),
    )


def _revenue_grouped(
    db: Session,
    profit_month_id: str | None,
    project_id: int | None,
):
    query = db.query(
        RevenueEvent.profit_month_id,
        func.sum(RevenueEvent.amount_micro_usdc),
    )
    if profit_month_id is not None:
        query = query.filter(RevenueEvent.profit_month_id == profit_month_id)
    if project_id is not None:
        query = query.filter(RevenueEvent.project_id == project_id)
    return query.group_by(RevenueEvent.profit_month_id).all()


def _expense_grouped(
    db: Session,
    profit_month_id: str | None,
    project_id: int | None,
):
    query = db.query(
        ExpenseEvent.profit_month_id,
        func.sum(ExpenseEvent.amount_micro_usdc),
    )
    if profit_month_id is not None:
        query = query.filter(ExpenseEvent.profit_month_id == profit_month_id)
    if project_id is not None:
        query = query.filter(ExpenseEvent.project_id == project_id)
    return query.group_by(ExpenseEvent.profit_month_id).all()


def _summary_item(
    profit_month_id: str,
    revenue_sum_micro_usdc: int,
    expense_sum_micro_usdc: int,
) -> AccountingMonthSummary:
    return AccountingMonthSummary(
        profit_month_id=profit_month_id,
        revenue_sum_micro_usdc=revenue_sum_micro_usdc,
        expense_sum_micro_usdc=expense_sum_micro_usdc,
        profit_sum_micro_usdc=revenue_sum_micro_usdc - expense_sum_micro_usdc,
    )


def _validate_month(profit_month_id: str) -> None:
    if not _MONTH_RE.fullmatch(profit_month_id):
        raise HTTPException(status_code=400, detail="profit_month_id must use YYYYMM format")
    month = int(profit_month_id[4:6])
    if month < 1 or month > 12:
        raise HTTPException(status_code=400, detail="profit_month_id month must be 01..12")
