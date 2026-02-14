from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Response
from sqlalchemy.orm import Session

from src.core.config import get_settings
from src.core.database import get_db
from src.models.project import Project, ProjectStatus
from src.models.project_capital_reconciliation_report import ProjectCapitalReconciliationReport
from src.models.project_revenue_reconciliation_report import ProjectRevenueReconciliationReport
from src.models.reconciliation_report import ReconciliationReport
from src.models.tx_outbox import TxOutbox
from src.schemas.alerts import AlertItem, AlertsData, AlertsResponse
from src.services.project_capital import is_reconciliation_fresh as is_capital_fresh
from src.services.project_revenue import is_reconciliation_fresh as is_revenue_fresh

router = APIRouter(prefix="/api/v1", tags=["public-system"])


@router.get(
    "/alerts",
    response_model=AlertsResponse,
    summary="Autonomy alerts (MVP)",
    description="Public read endpoint for machine/debug-friendly autonomy alerts (stale reconciliations, pending/failed tx).",
)
def get_alerts(response: Response, db: Session = Depends(get_db)) -> AlertsResponse:
    settings = get_settings()
    now = datetime.now(timezone.utc)

    items: list[AlertItem] = []

    if not (settings.funding_pool_contract_address or "").strip():
        items.append(
            AlertItem(
                alert_type="funding_pool_address_missing",
                severity="warning",
                message="FUNDING_POOL_CONTRACT_ADDRESS is not configured; stakers payouts will route to treasury.",
                ref=None,
                data=None,
                observed_at=now,
            )
        )

    # Latest per project (simple loop; small data).
    projects = db.query(Project).order_by(Project.project_id.asc()).all()

    cap_reports = (
        db.query(ProjectCapitalReconciliationReport)
        .order_by(ProjectCapitalReconciliationReport.computed_at.desc(), ProjectCapitalReconciliationReport.id.desc())
        .limit(5000)
        .all()
    )
    latest_cap: dict[int, ProjectCapitalReconciliationReport] = {}
    for r in cap_reports:
        latest_cap.setdefault(int(r.project_id), r)

    rev_reports = (
        db.query(ProjectRevenueReconciliationReport)
        .order_by(ProjectRevenueReconciliationReport.computed_at.desc(), ProjectRevenueReconciliationReport.id.desc())
        .limit(5000)
        .all()
    )
    latest_rev: dict[int, ProjectRevenueReconciliationReport] = {}
    for r in rev_reports:
        latest_rev.setdefault(int(r.project_id), r)

    for p in projects:
        if p.status != ProjectStatus.active:
            continue

        if not p.treasury_address:
            items.append(
                AlertItem(
                    alert_type="project_capital_treasury_missing",
                    severity="warning",
                    message="Project treasury_address is not configured (capital funding/outflows are blocked).",
                    ref=p.project_id,
                    data=None,
                    observed_at=now,
                )
            )
        else:
            rep = latest_cap.get(int(p.id))
            if rep is None:
                items.append(
                    AlertItem(
                        alert_type="project_capital_reconciliation_missing",
                        severity="warning",
                        message="Project capital reconciliation report is missing.",
                        ref=p.project_id,
                        observed_at=now,
                        data={"treasury_address": p.treasury_address},
                    )
                )
            else:
                fresh = is_capital_fresh(rep, settings.project_capital_reconciliation_max_age_seconds, now=now)
                if not fresh:
                    items.append(
                        AlertItem(
                            alert_type="project_capital_reconciliation_stale",
                            severity="warning",
                            message="Project capital reconciliation is stale.",
                            ref=p.project_id,
                            observed_at=now,
                            data={
                                "computed_at": rep.computed_at.isoformat(),
                                "ready": rep.ready,
                                "delta_micro_usdc": rep.delta_micro_usdc,
                            },
                        )
                    )
                if not rep.ready or (rep.delta_micro_usdc or 0) != 0:
                    items.append(
                        AlertItem(
                            alert_type="project_capital_not_reconciled",
                            severity="critical",
                            message="Project capital reconciliation is not strict-ready (outflows should be blocked).",
                            ref=p.project_id,
                            observed_at=now,
                            data={
                                "computed_at": rep.computed_at.isoformat(),
                                "ready": rep.ready,
                                "delta_micro_usdc": rep.delta_micro_usdc,
                                "blocked_reason": rep.blocked_reason,
                            },
                        )
                    )

        if not p.revenue_address:
            items.append(
                AlertItem(
                    alert_type="project_revenue_address_missing",
                    severity="info",
                    message="Project revenue_address is not configured (project_revenue payouts will be blocked).",
                    ref=p.project_id,
                    observed_at=now,
                )
            )
        else:
            rep = latest_rev.get(int(p.id))
            if rep is None:
                items.append(
                    AlertItem(
                        alert_type="project_revenue_reconciliation_missing",
                        severity="warning",
                        message="Project revenue reconciliation report is missing.",
                        ref=p.project_id,
                        observed_at=now,
                        data={"revenue_address": p.revenue_address},
                    )
                )
            else:
                fresh = is_revenue_fresh(rep, settings.project_revenue_reconciliation_max_age_seconds, now=now)
                if not fresh:
                    items.append(
                        AlertItem(
                            alert_type="project_revenue_reconciliation_stale",
                            severity="warning",
                            message="Project revenue reconciliation is stale.",
                            ref=p.project_id,
                            observed_at=now,
                            data={
                                "computed_at": rep.computed_at.isoformat(),
                                "ready": rep.ready,
                                "delta_micro_usdc": rep.delta_micro_usdc,
                            },
                        )
                    )
                if not rep.ready or (rep.delta_micro_usdc or 0) != 0:
                    items.append(
                        AlertItem(
                            alert_type="project_revenue_not_reconciled",
                            severity="critical",
                            message="Project revenue reconciliation is not strict-ready (project_revenue outflows should be blocked).",
                            ref=p.project_id,
                            observed_at=now,
                            data={
                                "computed_at": rep.computed_at.isoformat(),
                                "ready": rep.ready,
                                "delta_micro_usdc": rep.delta_micro_usdc,
                                "blocked_reason": rep.blocked_reason,
                            },
                        )
                    )

    # Platform settlement reconciliation (latest per month).
    reconciliations = (
        db.query(ReconciliationReport)
        .order_by(ReconciliationReport.profit_month_id.desc(), ReconciliationReport.computed_at.desc(), ReconciliationReport.id.desc())
        .limit(48)
        .all()
    )
    latest_platform_by_month: dict[str, ReconciliationReport] = {}
    for r in reconciliations:
        latest_platform_by_month.setdefault(r.profit_month_id, r)
    for month, rep in sorted(latest_platform_by_month.items(), reverse=True)[:12]:
        if not rep.ready or (rep.delta_micro_usdc or 0) != 0:
            items.append(
                AlertItem(
                    alert_type="platform_settlement_not_ready",
                    severity="warning",
                    message="Platform settlement reconciliation is not strict-ready (payout is blocked).",
                    ref=month,
                    observed_at=now,
                    data={
                        "ready": rep.ready,
                        "delta_micro_usdc": rep.delta_micro_usdc,
                        "blocked_reason": rep.blocked_reason,
                        "computed_at": rep.computed_at.isoformat(),
                    },
                )
            )

    # Tx outbox tasks (money-moving loop visibility).
    # Keep this lightweight; show recent failed + oldest pending/processing.
    pending = (
        db.query(TxOutbox)
        .filter(TxOutbox.status.in_(["pending", "processing"]))
        .order_by(TxOutbox.created_at.asc(), TxOutbox.id.asc())
        .limit(50)
        .all()
    )
    for t in pending:
        items.append(
            AlertItem(
                alert_type="tx_outbox_pending" if t.status == "pending" else "tx_outbox_processing",
                severity="warning" if t.status == "pending" else "critical",
                message=f"Tx outbox task is {t.status}.",
                ref=t.task_id,
                observed_at=now,
                data={
                    "task_type": t.task_type,
                    "attempts": t.attempts,
                    "locked_by": t.locked_by,
                    "locked_at": t.locked_at.isoformat() if t.locked_at else None,
                    "tx_hash": t.tx_hash,
                    "last_error_hint": t.last_error_hint,
                    "created_at": t.created_at.isoformat(),
                },
            )
        )

    failed = (
        db.query(TxOutbox)
        .filter(TxOutbox.status == "failed")
        .order_by(TxOutbox.updated_at.desc(), TxOutbox.id.desc())
        .limit(25)
        .all()
    )
    for t in failed:
        items.append(
            AlertItem(
                alert_type="tx_outbox_failed",
                severity="critical",
                message="Tx outbox task failed.",
                ref=t.task_id,
                observed_at=now,
                data={
                    "task_type": t.task_type,
                    "attempts": t.attempts,
                    "tx_hash": t.tx_hash,
                    "last_error_hint": t.last_error_hint,
                    "updated_at": t.updated_at.isoformat(),
                },
            )
        )

    response.headers["Cache-Control"] = "public, max-age=15"
    return AlertsResponse(success=True, data=AlertsData(items=items))
