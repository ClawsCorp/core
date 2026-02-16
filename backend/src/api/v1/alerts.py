from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Response
from sqlalchemy.orm import Session

from src.core.config import get_settings
from src.core.database import get_db
from src.models.indexer_cursor import IndexerCursor
from src.models.git_outbox import GitOutbox
from src.models.project import Project, ProjectStatus
from src.models.project_capital_reconciliation_report import ProjectCapitalReconciliationReport
from src.models.project_revenue_reconciliation_report import ProjectRevenueReconciliationReport
from src.models.reconciliation_report import ReconciliationReport
from src.models.tx_outbox import TxOutbox
from src.schemas.alerts import AlertItem, AlertsData, AlertsResponse
from src.services.project_capital import is_reconciliation_fresh as is_capital_fresh
from src.services.project_revenue import is_reconciliation_fresh as is_revenue_fresh

router = APIRouter(prefix="/api/v1", tags=["public-system"])


def _as_aware_utc(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt


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

    # Indexer health (cursor freshness). Without this, automation cannot observe chain reality.
    cursor = (
        db.query(IndexerCursor)
        .filter(IndexerCursor.cursor_key == "usdc_transfers")
        .order_by(IndexerCursor.updated_at.desc(), IndexerCursor.id.desc())
        .first()
    )
    if cursor is None:
        items.append(
            AlertItem(
                alert_type="usdc_indexer_cursor_missing",
                severity="warning",
                message="USDC indexer cursor is missing (indexer may not be running yet).",
                ref="usdc_transfers",
                observed_at=now,
            )
        )
    else:
        cursor_updated_at = _as_aware_utc(cursor.updated_at) or now
        age = int((now - cursor_updated_at).total_seconds())
        if age > int(settings.indexer_cursor_max_age_seconds):
            items.append(
                AlertItem(
                    alert_type="usdc_indexer_stale",
                    severity="critical",
                    message="USDC indexer cursor is stale (automation may be operating on outdated observed transfers).",
                    ref="usdc_transfers",
                    observed_at=now,
                    data={
                        "chain_id": int(cursor.chain_id),
                        "last_block_number": int(cursor.last_block_number),
                        "updated_at": cursor_updated_at.isoformat(),
                        "age_seconds": age,
                        "max_age_seconds": int(settings.indexer_cursor_max_age_seconds),
                    },
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

            # If we are under-funded, surface whether an autonomous profit deposit task exists.
            # This helps operators distinguish "waiting for tx-worker" vs "nothing is progressing".
            try:
                delta = int(rep.delta_micro_usdc or 0)
            except Exception:
                delta = 0
            if rep.blocked_reason == "balance_mismatch" and delta < 0:
                amount = -delta
                idem = f"deposit_profit:{month}:{amount}"
                task_exact = (
                    db.query(TxOutbox)
                    .filter(TxOutbox.idempotency_key == idem)
                    .order_by(TxOutbox.id.desc())
                    .first()
                )
                # Fallback by month prefix to avoid false "missing" alerts when delta changes
                # while a previous month-scoped deposit task is already pending/processing.
                task_month = (
                    db.query(TxOutbox)
                    .filter(TxOutbox.idempotency_key.like(f"deposit_profit:{month}:%"))
                    .order_by(TxOutbox.id.desc())
                    .first()
                )
                task = task_exact or task_month
                matched_exact_amount = task is not None and task.idempotency_key == idem

                if task is None:
                    # In direct submit mode (TX_OUTBOX_ENABLED=false), absence of tx_outbox task is expected.
                    # Avoid false-positive "missing task" warning in this mode.
                    if settings.tx_outbox_enabled:
                        items.append(
                            AlertItem(
                                alert_type="platform_profit_deposit_missing",
                                severity="warning",
                                message="Platform is under-funded but no profit deposit task exists yet (autonomy loop may not be running).",
                                ref=month,
                                observed_at=now,
                                data={"idempotency_key": idem, "amount_micro_usdc": amount},
                            )
                        )
                elif task.status in {"pending", "processing"}:
                    items.append(
                        AlertItem(
                            alert_type="platform_profit_deposit_pending",
                            severity="info",
                            message="Profit deposit is queued/processing; waiting for tx-worker.",
                            ref=month,
                            observed_at=now,
                            data={
                                "task_id": task.task_id,
                                "status": task.status,
                                "amount_micro_usdc": amount,
                                "tx_hash": task.tx_hash,
                                "attempts": task.attempts,
                                "locked_at": task.locked_at.isoformat() if task.locked_at else None,
                                "locked_by": task.locked_by,
                                "matched_exact_amount": matched_exact_amount,
                                "expected_idempotency_key": idem,
                            },
                        )
                    )
                elif task.status == "failed":
                    task_updated_at = _as_aware_utc(task.updated_at) or now
                    items.append(
                        AlertItem(
                            alert_type="platform_profit_deposit_failed",
                            severity="critical",
                            message="Profit deposit task failed; payout cannot proceed until fixed.",
                            ref=month,
                            observed_at=now,
                            data={
                                "task_id": task.task_id,
                                "status": task.status,
                                "amount_micro_usdc": amount,
                                "tx_hash": task.tx_hash,
                                "attempts": task.attempts,
                                "last_error_hint": task.last_error_hint,
                                "updated_at": task_updated_at.isoformat(),
                                "matched_exact_amount": matched_exact_amount,
                                "expected_idempotency_key": idem,
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
        created_at = _as_aware_utc(t.created_at) or now
        locked_at = _as_aware_utc(t.locked_at)
        created_age = int((now - created_at).total_seconds())
        processing_age = int((now - locked_at).total_seconds()) if locked_at else None
        if t.status == "pending":
            severity = "critical" if created_age > int(settings.tx_outbox_pending_max_age_seconds) else "warning"
            alert_type = "tx_outbox_pending_stale" if severity == "critical" else "tx_outbox_pending"
        else:
            severity = "critical" if (processing_age or 0) > int(settings.tx_outbox_processing_max_age_seconds) else "warning"
            alert_type = "tx_outbox_processing_stale" if severity == "critical" else "tx_outbox_processing"

        items.append(
            AlertItem(
                alert_type=alert_type,
                severity=severity,
                message=f"Tx outbox task is {t.status}.",
                ref=t.task_id,
                observed_at=now,
                data={
                    "task_type": t.task_type,
                    "attempts": t.attempts,
                    "locked_by": t.locked_by,
                    "locked_at": locked_at.isoformat() if locked_at else None,
                    "age_seconds": created_age,
                    "processing_age_seconds": processing_age,
                    "tx_hash": t.tx_hash,
                    "last_error_hint": t.last_error_hint,
                    "created_at": created_at.isoformat(),
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
        task_updated_at = _as_aware_utc(t.updated_at) or now
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
                    "updated_at": task_updated_at.isoformat(),
                },
            )
        )

    # Git outbox tasks (repo automation visibility).
    git_pending = (
        db.query(GitOutbox)
        .filter(GitOutbox.status.in_(["pending", "processing"]))
        .order_by(GitOutbox.created_at.asc(), GitOutbox.id.asc())
        .limit(50)
        .all()
    )
    for t in git_pending:
        created_at = _as_aware_utc(t.created_at) or now
        locked_at = _as_aware_utc(t.locked_at)
        created_age = int((now - created_at).total_seconds())
        processing_age = int((now - locked_at).total_seconds()) if locked_at else None
        if t.status == "pending":
            severity = "critical" if created_age > int(settings.git_outbox_pending_max_age_seconds) else "warning"
            alert_type = "git_outbox_pending_stale" if severity == "critical" else "git_outbox_pending"
        else:
            severity = "critical" if (processing_age or 0) > int(settings.git_outbox_processing_max_age_seconds) else "warning"
            alert_type = "git_outbox_processing_stale" if severity == "critical" else "git_outbox_processing"

        items.append(
            AlertItem(
                alert_type=alert_type,
                severity=severity,
                message=f"Git outbox task is {t.status}.",
                ref=t.task_id,
                observed_at=now,
                data={
                    "task_type": t.task_type,
                    "attempts": t.attempts,
                    "locked_by": t.locked_by,
                    "locked_at": locked_at.isoformat() if locked_at else None,
                    "age_seconds": created_age,
                    "processing_age_seconds": processing_age,
                    "last_error_hint": t.last_error_hint,
                    "project_num": t.project_id,
                    "requested_by_agent_num": t.requested_by_agent_id,
                    "created_at": created_at.isoformat(),
                },
            )
        )

    git_failed = (
        db.query(GitOutbox)
        .filter(GitOutbox.status == "failed")
        .order_by(GitOutbox.updated_at.desc(), GitOutbox.id.desc())
        .limit(25)
        .all()
    )
    for t in git_failed:
        task_updated_at = _as_aware_utc(t.updated_at) or now
        items.append(
            AlertItem(
                alert_type="git_outbox_failed",
                severity="critical",
                message="Git outbox task failed.",
                ref=t.task_id,
                observed_at=now,
                data={
                    "task_type": t.task_type,
                    "attempts": t.attempts,
                    "last_error_hint": t.last_error_hint,
                    "project_num": t.project_id,
                    "requested_by_agent_num": t.requested_by_agent_id,
                    "updated_at": task_updated_at.isoformat(),
                },
            )
        )

    response.headers["Cache-Control"] = "public, max-age=15"
    return AlertsResponse(success=True, data=AlertsData(items=items))
