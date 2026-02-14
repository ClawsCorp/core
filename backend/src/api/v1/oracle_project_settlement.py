from __future__ import annotations

import re
from datetime import datetime, timezone
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import func
from sqlalchemy.orm import Session

from src.api.v1.dependencies import require_oracle_hmac
from src.core.audit import record_audit
from src.core.database import get_db
from src.models.expense_event import ExpenseEvent
from src.models.project import Project
from src.models.project_settlement import ProjectSettlement
from src.models.revenue_event import RevenueEvent
from src.schemas.project_settlement import ProjectSettlementPublic

router = APIRouter(prefix="/api/v1/oracle", tags=["oracle-project-settlement"])

_MONTH_RE = re.compile(r"^\d{6}$")


@router.post(
    "/projects/{project_id}/settlement/{profit_month_id}",
    response_model=ProjectSettlementPublic,
    summary="Compute project settlement for month (oracle)",
    description="Oracle/HMAC-protected compute endpoint for a project's monthly profit summary (ledger-only). Append-only.",
)
def compute_project_settlement(
    project_id: str,
    profit_month_id: str,
    request: Request,
    _: str = Depends(require_oracle_hmac),
    db: Session = Depends(get_db),
) -> ProjectSettlementPublic:
    _validate_month(profit_month_id)

    project = db.query(Project).filter(Project.project_id == project_id).first()
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")

    revenue_sum = int(
        db.query(func.coalesce(func.sum(RevenueEvent.amount_micro_usdc), 0))
        .filter(RevenueEvent.profit_month_id == profit_month_id, RevenueEvent.project_id == project.id)
        .scalar()
        or 0
    )
    expense_sum = int(
        db.query(func.coalesce(func.sum(ExpenseEvent.amount_micro_usdc), 0))
        .filter(ExpenseEvent.profit_month_id == profit_month_id, ExpenseEvent.project_id == project.id)
        .scalar()
        or 0
    )
    profit_sum = revenue_sum - expense_sum

    settlement = ProjectSettlement(
        project_id=project.id,
        profit_month_id=profit_month_id,
        revenue_sum_micro_usdc=revenue_sum,
        expense_sum_micro_usdc=expense_sum,
        profit_sum_micro_usdc=profit_sum,
        profit_nonnegative=profit_sum >= 0,
        note=None,
    )
    db.add(settlement)

    request_id = request.headers.get("X-Request-Id") or request.headers.get("X-Request-ID") or str(uuid4())
    idempotency_key = f"project_settlement:{project.project_id}:{profit_month_id}:{request_id}"
    _record_oracle_audit(request, db, idempotency_key=idempotency_key, commit=False)
    db.commit()
    db.refresh(settlement)

    return ProjectSettlementPublic(
        project_id=project.project_id,
        profit_month_id=settlement.profit_month_id,
        revenue_sum_micro_usdc=int(settlement.revenue_sum_micro_usdc),
        expense_sum_micro_usdc=int(settlement.expense_sum_micro_usdc),
        profit_sum_micro_usdc=int(settlement.profit_sum_micro_usdc),
        profit_nonnegative=bool(settlement.profit_nonnegative),
        note=settlement.note,
        computed_at=settlement.computed_at,
    )


def _record_oracle_audit(
    request: Request,
    db: Session,
    *,
    idempotency_key: str,
    commit: bool = True,
) -> None:
    signature_status = getattr(request.state, "signature_status", "invalid")
    request_id = request.headers.get("X-Request-Id") or request.headers.get("X-Request-ID") or str(uuid4())
    body_hash = getattr(request.state, "body_hash", "")
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


def _validate_month(profit_month_id: str) -> None:
    if not _MONTH_RE.fullmatch(profit_month_id):
        raise HTTPException(status_code=400, detail="profit_month_id must use YYYYMM format")
    month = int(profit_month_id[4:6])
    if month < 1 or month > 12:
        raise HTTPException(status_code=400, detail="profit_month_id month must be 01..12")

