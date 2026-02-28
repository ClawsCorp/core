from __future__ import annotations

import json
from datetime import datetime, timezone
from urllib import error as urlerror
from urllib import request as urlrequest

from fastapi import APIRouter, Depends, Response
from sqlalchemy import func
from sqlalchemy.orm import Session

from src.core.config import get_settings
from src.core.database import get_db
from src.models.indexer_cursor import IndexerCursor
from src.models.bounty import Bounty, BountyStatus
from src.models.git_outbox import GitOutbox
from src.models.marketing_fee_accrual_event import MarketingFeeAccrualEvent
from src.models.project import Project, ProjectStatus
from src.models.project_capital_reconciliation_report import ProjectCapitalReconciliationReport
from src.models.project_revenue_reconciliation_report import ProjectRevenueReconciliationReport
from src.models.reconciliation_report import ReconciliationReport
from src.models.distribution_creation import DistributionCreation
from src.models.distribution_execution import DistributionExecution
from src.models.tx_outbox import TxOutbox
from src.schemas.alerts import AlertItem, AlertsData, AlertsResponse
from src.services.project_capital import is_reconciliation_fresh as is_capital_fresh
from src.services.project_revenue import is_reconciliation_fresh as is_revenue_fresh

router = APIRouter(prefix="/api/v1", tags=["public-system"])


def _as_aware_utc(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt


def _fetch_dividend_distributor_owner(settings) -> tuple[str | None, str | None]:
    rpc_url = str(settings.base_sepolia_rpc_url or "").strip()
    contract_address = str(settings.dividend_distributor_contract_address or "").strip()
    if not rpc_url or not contract_address:
        return None, "config_missing"

    body = json.dumps(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "eth_call",
            "params": [
                {
                    "to": contract_address,
                    "data": "0x8da5cb5b",  # owner()
                },
                "latest",
            ],
        },
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    req = urlrequest.Request(
        rpc_url,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlrequest.urlopen(req, timeout=10) as resp:
            payload = json.loads(resp.read().decode("utf-8", errors="replace"))
    except (urlerror.URLError, TimeoutError, ValueError):
        return None, "rpc_error"

    result = str((payload or {}).get("result") or "").strip()
    if not result.startswith("0x") or len(result) < 66:
        return None, "invalid_result"
    owner = "0x" + result[-40:]
    return owner, None


def _is_failed_tx_outbox_superseded(db: Session, task: TxOutbox) -> bool:
    if task.task_type not in {"create_distribution", "execute_distribution"}:
        return False

    try:
        payload = json.loads(task.payload_json or "{}")
    except ValueError:
        payload = {}
    profit_month_id = str((payload or {}).get("profit_month_id") or "").strip()
    if not profit_month_id:
        return False

    if task.task_type == "create_distribution":
        existing = (
            db.query(DistributionCreation.id)
            .filter(DistributionCreation.profit_month_id == profit_month_id)
            .first()
        )
        return existing is not None

    existing = (
        db.query(DistributionExecution.id)
        .filter(
            DistributionExecution.profit_month_id == profit_month_id,
            DistributionExecution.status.in_(["submitted", "already_distributed"]),
        )
        .first()
    )
    return existing is not None


def _is_failed_git_outbox_resolved(db: Session, task: GitOutbox) -> bool:
    try:
        payload = json.loads(task.payload_json or "{}")
    except ValueError:
        payload = {}
    try:
        result = json.loads(task.result_json or "{}")
    except ValueError:
        result = {}

    bounty_id = str((payload or {}).get("bounty_id") or "").strip()
    if not bounty_id:
        return False

    query = db.query(Bounty).filter(Bounty.bounty_id == bounty_id)
    if task.project_id is not None:
        query = query.filter(Bounty.project_id == task.project_id)
    bounty = query.first()
    if bounty is None:
        return False
    if bounty.status not in {
        BountyStatus.submitted,
        BountyStatus.eligible_for_payout,
        BountyStatus.paid,
    }:
        return False

    commit_sha = str(task.commit_sha or "").strip().lower()
    if commit_sha and str(bounty.merge_sha or "").strip().lower() == commit_sha:
        return True

    pr_url = str((result or {}).get("pr_url") or "").strip()
    if pr_url and str(bounty.pr_url or "").strip() == pr_url:
        return True

    return False


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

    if int(settings.marketing_fee_bps or 0) > 0 and not (settings.marketing_treasury_address or "").strip():
        items.append(
            AlertItem(
                alert_type="marketing_treasury_address_missing",
                severity="warning",
                message="MARKETING_TREASURY_ADDRESS is not configured; 1% marketing accrual cannot be settled on-chain.",
                ref=None,
                data={"marketing_fee_bps": int(settings.marketing_fee_bps or 0)},
                observed_at=now,
            )
        )

    if not (settings.safe_owner_address or "").strip():
        items.append(
            AlertItem(
                alert_type="safe_owner_address_missing",
                severity="warning",
                message="SAFE_OWNER_ADDRESS is not configured; on-chain ownership is still not pinned to Safe.",
                ref=None,
                data=None,
                observed_at=now,
            )
        )
    else:
        current_owner, owner_error = _fetch_dividend_distributor_owner(settings)
        if owner_error == "config_missing":
            items.append(
                AlertItem(
                    alert_type="dividend_distributor_owner_check_unavailable",
                    severity="warning",
                    message="Cannot verify DividendDistributor owner because RPC or contract address is not configured.",
                    ref=None,
                    data=None,
                    observed_at=now,
                )
            )
        elif owner_error is not None:
            items.append(
                AlertItem(
                    alert_type="dividend_distributor_owner_check_failed",
                    severity="warning",
                    message="DividendDistributor owner check failed; Safe custody cannot be verified.",
                    ref=None,
                    data={"error": owner_error},
                    observed_at=now,
                )
            )
        elif str(current_owner or "").lower() != str(settings.safe_owner_address or "").lower():
            items.append(
                AlertItem(
                    alert_type="dividend_distributor_safe_owner_mismatch",
                    severity="warning",
                    message="DividendDistributor owner does not match SAFE_OWNER_ADDRESS yet.",
                    ref=None,
                    data={
                        "current_owner": current_owner,
                        "expected_safe_owner": settings.safe_owner_address,
                    },
                    observed_at=now,
                )
            )

    total_marketing_fee = int(
        db.query(func.coalesce(func.sum(MarketingFeeAccrualEvent.fee_amount_micro_usdc), 0)).scalar() or 0
    )
    sent_rows = (
        db.query(TxOutbox.payload_json)
        .filter(
            TxOutbox.task_type == "deposit_marketing_fee",
            TxOutbox.status.in_(["pending", "processing", "succeeded"]),
        )
        .all()
    )
    sent_marketing_fee = 0
    for (payload_json,) in sent_rows:
        try:
            payload = json.loads(payload_json or "{}")
            sent_marketing_fee += int(payload.get("amount_micro_usdc") or 0)
        except (ValueError, TypeError):
            continue
    pending_marketing_fee = max(0, int(total_marketing_fee) - int(sent_marketing_fee))

    if pending_marketing_fee > 0:
        items.append(
            AlertItem(
                alert_type="marketing_fee_accrued",
                severity="info",
                message="Marketing fee accrual has pending balance from inflows.",
                ref=None,
                data={
                    "marketing_fee_bps": int(settings.marketing_fee_bps or 0),
                    "total_fee_micro_usdc": total_marketing_fee,
                    "sent_fee_micro_usdc": sent_marketing_fee,
                    "pending_fee_micro_usdc": pending_marketing_fee,
                    "events_count": int(db.query(func.count(MarketingFeeAccrualEvent.id)).scalar() or 0),
                    "marketing_treasury_address": settings.marketing_treasury_address,
                },
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
            try:
                delta = int(rep.delta_micro_usdc or 0)
            except Exception:
                delta = 0

            # Zero-profit months can legitimately observe positive carryover balance
            # from previously funded months. Keep visibility as info, not warning.
            if rep.blocked_reason == "balance_mismatch" and delta > 0 and int(rep.profit_sum_micro_usdc or 0) <= 0:
                items.append(
                    AlertItem(
                        alert_type="platform_settlement_carryover_balance",
                        severity="info",
                        message="Platform distributor has positive carryover balance in a zero-profit month.",
                        ref=month,
                        observed_at=now,
                        data={
                            "ready": rep.ready,
                            "delta_micro_usdc": rep.delta_micro_usdc,
                            "blocked_reason": rep.blocked_reason,
                            "profit_sum_micro_usdc": rep.profit_sum_micro_usdc,
                            "computed_at": rep.computed_at.isoformat(),
                        },
                    )
                )
                continue

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
        if _is_failed_tx_outbox_superseded(db, t):
            continue
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

    blocked_tasks = (
        db.query(TxOutbox)
        .filter(TxOutbox.status == "blocked")
        .order_by(TxOutbox.updated_at.desc(), TxOutbox.id.desc())
        .limit(25)
        .all()
    )
    for t in blocked_tasks:
        task_updated_at = _as_aware_utc(t.updated_at) or now
        items.append(
            AlertItem(
                alert_type="tx_outbox_blocked",
                severity="warning",
                message="Tx outbox task is blocked and requires manual/Safe action.",
                ref=t.task_id,
                observed_at=now,
                data={
                    "task_type": t.task_type,
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
        if _is_failed_git_outbox_resolved(db, t):
            continue
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
