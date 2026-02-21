from __future__ import annotations

import re
import secrets
from datetime import timezone
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import func
from sqlalchemy.orm import Session

from src.api.v1.dependencies import require_oracle_hmac
from src.core.audit import record_audit
from src.core.config import get_settings
from src.core.database import get_db
from src.core.db_utils import insert_or_get_by_unique
from src.models.observed_usdc_transfer import ObservedUsdcTransfer
from src.models.project import Project
from src.models.project_capital_event import ProjectCapitalEvent
from src.models.project_capital_reconciliation_report import ProjectCapitalReconciliationReport
from src.models.project_funding_deposit import ProjectFundingDeposit
from src.models.project_funding_round import ProjectFundingRound
from src.schemas.oracle_projects import (
    ProjectCapitalReconciliationRunResponse,
    ProjectCapitalSyncData,
    ProjectCapitalSyncResponse,
    ProjectTreasurySetData,
    ProjectTreasurySetRequest,
    ProjectTreasurySetResponse,
)
from src.schemas.project import ProjectCapitalEventCreateRequest, ProjectCapitalEventDetailResponse, ProjectCapitalEventPublic
from src.schemas.project import ProjectCapitalReconciliationReportPublic
from src.schemas.project_funding import (
    ProjectFundingRoundCloseRequest,
    ProjectFundingRoundCreateRequest,
    ProjectFundingRoundCreateResponse,
    ProjectFundingRoundPublic,
)
from src.services.blockchain import (
    BlockchainConfigError,
    BlockchainReadError,
    get_usdc_balance_micro_usdc,
    read_block_timestamp_utc,
)
from src.services.project_capital import get_latest_project_capital_reconciliation, is_reconciliation_fresh
from src.services.marketing_fee import accrue_marketing_fee_event, build_marketing_fee_idempotency_key

router = APIRouter(prefix="/api/v1/oracle", tags=["oracle-project-capital"])

_MONTH_RE = re.compile(r"^\d{6}$")
_ADDRESS_RE = re.compile(r"^0x[a-f0-9]{40}$")


@router.post("/project-capital-events", response_model=ProjectCapitalEventDetailResponse)
async def create_project_capital_event(
    payload: ProjectCapitalEventCreateRequest,
    request: Request,
    _: str = Depends(require_oracle_hmac),
    db: Session = Depends(get_db),
) -> ProjectCapitalEventDetailResponse:
    if payload.profit_month_id is not None:
        _validate_month(payload.profit_month_id)
    if payload.delta_micro_usdc == 0:
        raise HTTPException(status_code=400, detail="delta_micro_usdc must be non-zero")

    project = db.query(Project).filter(Project.project_id == payload.project_id).first()
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")

    request_id = request.headers.get("X-Request-Id") or request.headers.get("X-Request-ID") or str(uuid4())
    body_hash = request.state.body_hash

    # Fail-closed: any project capital outflow requires a fresh strict-ready reconciliation
    # for the project's treasury anchor. This reduces the risk of drifting the ledger away
    # from on-chain reality before money-moving actions.
    if payload.delta_micro_usdc < 0:
        blocked_reason = _ensure_project_capital_outflow_reconciliation_gate(db, project.id)
        if blocked_reason is not None:
            compact_error_hint = (
                f"br={blocked_reason};"
                f"p={project.project_id};"
                f"idem={payload.idempotency_key};"
                f"d={payload.delta_micro_usdc};"
                f"src={payload.source}"
            )
            _record_oracle_audit(
                request,
                db,
                body_hash,
                request_id,
                payload.idempotency_key,
                error_hint=compact_error_hint,
                commit=False,
            )
            db.commit()
            return ProjectCapitalEventDetailResponse(
                success=False,
                data=None,
                blocked_reason=blocked_reason,
            )

    event = ProjectCapitalEvent(
        event_id=payload.event_id or _generate_event_id(db),
        idempotency_key=payload.idempotency_key,
        profit_month_id=payload.profit_month_id,
        project_id=project.id,
        delta_micro_usdc=payload.delta_micro_usdc,
        source=payload.source,
        evidence_tx_hash=payload.evidence_tx_hash,
        evidence_url=payload.evidence_url,
    )
    event, _ = insert_or_get_by_unique(
        db,
        instance=event,
        model=ProjectCapitalEvent,
        unique_filter={"idempotency_key": payload.idempotency_key},
    )
    if int(payload.delta_micro_usdc) > 0:
        _mfee_row, _mfee_created, _mfee_amount = accrue_marketing_fee_event(
            db,
            idempotency_key=build_marketing_fee_idempotency_key(
                prefix="mfee:project_capital_event",
                source_idempotency_key=payload.idempotency_key,
            ),
            project_id=project.id,
            profit_month_id=payload.profit_month_id,
            bucket="project_capital",
            source=payload.source,
            gross_amount_micro_usdc=int(payload.delta_micro_usdc),
            chain_id=None,
            tx_hash=payload.evidence_tx_hash.lower() if payload.evidence_tx_hash else None,
            log_index=None,
            evidence_url=payload.evidence_url or f"project_capital_event:{payload.idempotency_key}",
        )
    _record_oracle_audit(request, db, body_hash, request_id, payload.idempotency_key, commit=False)
    db.commit()
    db.refresh(event)
    return ProjectCapitalEventDetailResponse(success=True, data=_public(project.project_id, event), blocked_reason=None)


@router.post("/project-capital-events/sync", response_model=ProjectCapitalSyncResponse)
async def sync_project_capital_from_observed_usdc_transfers(
    request: Request,
    _: str = Depends(require_oracle_hmac),
    db: Session = Depends(get_db),
) -> ProjectCapitalSyncResponse:
    """
    MVP automation helper: turn observed on-chain USDC transfers into project treasury addresses into append-only
    `project_capital_events` (capital inflows).

    Safe to run repeatedly: idempotent per (chain_id, tx_hash, log_index, project_id).
    """
    request_id = request.headers.get("X-Request-Id") or request.headers.get("X-Request-ID") or str(uuid4())
    body_hash = request.state.body_hash
    sync_idem = request.headers.get("Idempotency-Key") or f"project_capital_sync:{request_id}"

    projects = (
        db.query(Project.id, Project.project_id, Project.treasury_address)
        .filter(Project.treasury_address.isnot(None))
        .all()
    )
    addr_to_project: dict[str, tuple[int, str]] = {}
    project_db_ids: list[int] = []
    for pid, public_id, addr in projects:
        if addr:
            addr_to_project[str(addr).lower()] = (int(pid), str(public_id))
            project_db_ids.append(int(pid))

    if not addr_to_project:
        _record_oracle_audit(request, db, body_hash, request_id, sync_idem, commit=True)
        return ProjectCapitalSyncResponse(
            success=True,
            data=ProjectCapitalSyncData(
                transfers_seen=0,
                capital_events_inserted=0,
                marketing_fee_events_inserted=0,
                marketing_fee_total_micro_usdc=0,
                projects_with_treasury_count=0,
            ),
        )

    # Attach funding deposits to the latest open funding round (if any).
    open_round_by_project: dict[int, int] = {}
    if project_db_ids:
        rounds = (
            db.query(ProjectFundingRound)
            .filter(ProjectFundingRound.project_id.in_(project_db_ids), ProjectFundingRound.status == "open")
            .order_by(ProjectFundingRound.opened_at.desc(), ProjectFundingRound.id.desc())
            .all()
        )
        for r in rounds:
            pid = int(r.project_id)
            if pid not in open_round_by_project:
                open_round_by_project[pid] = int(r.id)

    transfers = (
        db.query(ObservedUsdcTransfer)
        .filter(ObservedUsdcTransfer.to_address.in_(list(addr_to_project.keys())))
        .order_by(ObservedUsdcTransfer.block_number.desc(), ObservedUsdcTransfer.log_index.desc())
        .limit(1000)
        .all()
    )

    block_ts_cache: dict[int, str] = {}
    transfers_seen = 0
    inserted = 0
    marketing_fee_events_inserted = 0
    marketing_fee_total_micro_usdc = 0

    for t in transfers:
        dest = str(t.to_address).lower()
        if dest not in addr_to_project:
            continue
        project_db_id, project_public_id = addr_to_project[dest]
        transfers_seen += 1

        bn = int(t.block_number)
        if bn in block_ts_cache:
            profit_month_id = block_ts_cache[bn]
        else:
            try:
                ts = read_block_timestamp_utc(bn)
                profit_month_id = ts.astimezone(timezone.utc).strftime("%Y%m")
            except BlockchainReadError:
                profit_month_id = t.observed_at.astimezone(timezone.utc).strftime("%Y%m")
            block_ts_cache[bn] = profit_month_id

        # Extra safety: if this on-chain transfer has already been accounted for in the ledger
        # (e.g. manual oracle ingestion using the tx hash as evidence), skip inserting a duplicate
        # capital event even if the idempotency key differs.
        #
        # This prevents double-counting when `ObservedUsdcTransfer` arrives late (indexer lag) but
        # a capital inflow has already been recorded append-only via another path.
        already_accounted = (
            db.query(ProjectCapitalEvent.id)
            .filter(
                ProjectCapitalEvent.project_id == project_db_id,
                ProjectCapitalEvent.evidence_tx_hash == str(t.tx_hash).lower(),
                ProjectCapitalEvent.delta_micro_usdc == int(t.amount_micro_usdc),
            )
            .first()
        )
        if already_accounted is None:
            idem = f"pcap:deposit:{int(t.chain_id)}:{t.tx_hash}:{int(t.log_index)}:to:{project_public_id}"
            event = ProjectCapitalEvent(
                event_id=_generate_event_id(db),
                idempotency_key=idem,
                profit_month_id=profit_month_id,
                project_id=project_db_id,
                delta_micro_usdc=int(t.amount_micro_usdc),
                source="treasury_usdc_deposit",
                evidence_tx_hash=str(t.tx_hash),
                evidence_url=f"usdc_transfer:{t.tx_hash}#log:{int(t.log_index)};to:{project_public_id}",
            )
            _row, created = insert_or_get_by_unique(
                db,
                instance=event,
                model=ProjectCapitalEvent,
                unique_filter={"idempotency_key": idem},
            )
            if created:
                inserted += 1

        dep = ProjectFundingDeposit(
            deposit_id=f"pfdep_{secrets.token_hex(8)}",
            project_id=project_db_id,
            funding_round_id=open_round_by_project.get(project_db_id),
            observed_transfer_id=int(t.id),
            chain_id=int(t.chain_id),
            from_address=str(t.from_address).lower(),
            to_address=str(t.to_address).lower(),
            amount_micro_usdc=int(t.amount_micro_usdc),
            block_number=int(t.block_number),
            tx_hash=str(t.tx_hash).lower(),
            log_index=int(t.log_index),
            observed_at=t.observed_at,
        )
        insert_or_get_by_unique(
            db,
            instance=dep,
            model=ProjectFundingDeposit,
            unique_filter={"observed_transfer_id": int(t.id)},
        )

        _mfee_row, mfee_created, mfee_amount = accrue_marketing_fee_event(
            db,
            idempotency_key=f"mfee:pcap:{int(t.chain_id)}:{str(t.tx_hash).lower()}:{int(t.log_index)}:to:{project_public_id}",
            project_id=project_db_id,
            profit_month_id=profit_month_id,
            bucket="project_capital",
            source="treasury_usdc_deposit",
            gross_amount_micro_usdc=int(t.amount_micro_usdc),
            chain_id=int(t.chain_id),
            tx_hash=str(t.tx_hash).lower(),
            log_index=int(t.log_index),
            evidence_url=f"usdc_transfer:{t.tx_hash}#log:{int(t.log_index)};to:{project_public_id}",
        )
        if mfee_created:
            marketing_fee_events_inserted += 1
        marketing_fee_total_micro_usdc += int(mfee_amount)

    _record_oracle_audit(request, db, body_hash, request_id, sync_idem, commit=False)
    db.commit()
    return ProjectCapitalSyncResponse(
        success=True,
        data=ProjectCapitalSyncData(
            transfers_seen=transfers_seen,
            capital_events_inserted=inserted,
            marketing_fee_events_inserted=marketing_fee_events_inserted,
            marketing_fee_total_micro_usdc=marketing_fee_total_micro_usdc,
            projects_with_treasury_count=len(addr_to_project),
        ),
    )


def _funding_round_public(project_id: str, row: ProjectFundingRound) -> ProjectFundingRoundPublic:
    return ProjectFundingRoundPublic(
        round_id=row.round_id,
        project_id=project_id,
        title=row.title,
        status=row.status,
        cap_micro_usdc=int(row.cap_micro_usdc) if row.cap_micro_usdc is not None else None,
        opened_at=row.opened_at,
        closed_at=row.closed_at,
        created_at=row.created_at,
    )


@router.post("/projects/{project_id}/funding-rounds", response_model=ProjectFundingRoundCreateResponse)
async def open_project_funding_round(
    project_id: str,
    payload: ProjectFundingRoundCreateRequest,
    request: Request,
    _: str = Depends(require_oracle_hmac),
    db: Session = Depends(get_db),
) -> ProjectFundingRoundCreateResponse:
    project = db.query(Project).filter(Project.project_id == project_id).first()
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")

    request_id = request.headers.get("X-Request-Id") or request.headers.get("X-Request-ID") or str(uuid4())
    body_hash = request.state.body_hash

    existing_open = (
        db.query(ProjectFundingRound)
        .filter(ProjectFundingRound.project_id == project.id, ProjectFundingRound.status == "open")
        .order_by(ProjectFundingRound.opened_at.desc(), ProjectFundingRound.id.desc())
        .first()
    )
    if existing_open is not None and str(existing_open.idempotency_key) != str(payload.idempotency_key):
        _record_oracle_audit(request, db, body_hash, request_id, payload.idempotency_key, commit=True)
        return ProjectFundingRoundCreateResponse(success=False, data=None, blocked_reason="funding_round_already_open")

    row = ProjectFundingRound(
        round_id=f"fr_{secrets.token_hex(8)}",
        idempotency_key=payload.idempotency_key,
        project_id=int(project.id),
        title=payload.title,
        status="open",
        cap_micro_usdc=int(payload.cap_micro_usdc) if payload.cap_micro_usdc is not None else None,
    )
    row, _ = insert_or_get_by_unique(
        db,
        instance=row,
        model=ProjectFundingRound,
        unique_filter={"idempotency_key": payload.idempotency_key},
    )
    _record_oracle_audit(request, db, body_hash, request_id, payload.idempotency_key, commit=False)
    db.commit()
    db.refresh(row)
    return ProjectFundingRoundCreateResponse(success=True, data=_funding_round_public(project.project_id, row), blocked_reason=None)


@router.post("/projects/{project_id}/funding-rounds/{round_id}/close", response_model=ProjectFundingRoundCreateResponse)
async def close_project_funding_round(
    project_id: str,
    round_id: str,
    payload: ProjectFundingRoundCloseRequest,
    request: Request,
    _: str = Depends(require_oracle_hmac),
    db: Session = Depends(get_db),
) -> ProjectFundingRoundCreateResponse:
    project = db.query(Project).filter(Project.project_id == project_id).first()
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")

    row = (
        db.query(ProjectFundingRound)
        .filter(ProjectFundingRound.project_id == project.id, ProjectFundingRound.round_id == round_id)
        .first()
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Funding round not found")

    request_id = request.headers.get("X-Request-Id") or request.headers.get("X-Request-ID") or str(uuid4())
    body_hash = request.state.body_hash

    if row.status != "closed":
        row.status = "closed"
        row.closed_at = func.now()
        db.add(row)

    _record_oracle_audit(request, db, body_hash, request_id, payload.idempotency_key, commit=False)
    db.commit()
    db.refresh(row)
    return ProjectFundingRoundCreateResponse(success=True, data=_funding_round_public(project.project_id, row), blocked_reason=None)


@router.post("/projects/{project_id}/treasury", response_model=ProjectTreasurySetResponse)
async def set_project_treasury_address(
    project_id: str,
    payload: ProjectTreasurySetRequest,
    request: Request,
    _: str = Depends(require_oracle_hmac),
    db: Session = Depends(get_db),
) -> ProjectTreasurySetResponse:
    project = db.query(Project).filter(Project.project_id == project_id).first()
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")

    normalized = payload.treasury_address.strip().lower()
    idempotency_key = f"project_treasury:{project_id}:{normalized}"
    request_id = request.headers.get("X-Request-Id") or request.headers.get("X-Request-ID") or str(uuid4())
    body_hash = request.state.body_hash

    if not _ADDRESS_RE.fullmatch(normalized):
        _record_oracle_audit(request, db, body_hash, request_id, idempotency_key, commit=False)
        db.commit()
        return ProjectTreasurySetResponse(
            success=False,
            data=ProjectTreasurySetData(
                project_id=project_id,
                treasury_address=normalized,
                status="set",
                blocked_reason="invalid_address",
            ),
        )

    status = "unchanged" if project.treasury_address == normalized else "set"
    project.treasury_address = normalized
    _record_oracle_audit(request, db, body_hash, request_id, idempotency_key, commit=False)
    db.commit()
    return ProjectTreasurySetResponse(
        success=True,
        data=ProjectTreasurySetData(project_id=project_id, treasury_address=normalized, status=status),
    )


@router.post("/projects/{project_id}/capital/reconciliation", response_model=ProjectCapitalReconciliationRunResponse)
async def reconcile_project_capital(
    project_id: str,
    request: Request,
    _: str = Depends(require_oracle_hmac),
    db: Session = Depends(get_db),
) -> ProjectCapitalReconciliationRunResponse:
    project = db.query(Project).filter(Project.project_id == project_id).first()
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")

    request_id = request.headers.get("X-Request-Id") or request.headers.get("X-Request-ID") or str(uuid4())
    body_hash = request.state.body_hash
    idempotency_key = f"project_capital_reconciliation:{project_id}:{request_id}"

    if not project.treasury_address:
        report = ProjectCapitalReconciliationReport(
            project_id=project.id,
            treasury_address="",
            ledger_balance_micro_usdc=None,
            onchain_balance_micro_usdc=None,
            delta_micro_usdc=None,
            ready=False,
            blocked_reason="treasury_not_configured",
        )
        db.add(report)
        _record_oracle_audit(request, db, body_hash, request_id, idempotency_key, commit=False)
        db.commit()
        db.refresh(report)
        return ProjectCapitalReconciliationRunResponse(success=True, data=_recon_public(project_id, report))

    ledger_balance = int(
        db.query(func.coalesce(func.sum(ProjectCapitalEvent.delta_micro_usdc), 0))
        .filter(ProjectCapitalEvent.project_id == project.id)
        .scalar()
        or 0
    )

    try:
        onchain = get_usdc_balance_micro_usdc(project.treasury_address)
    except BlockchainConfigError:
        report = ProjectCapitalReconciliationReport(
            project_id=project.id,
            treasury_address=project.treasury_address,
            ledger_balance_micro_usdc=None,
            onchain_balance_micro_usdc=None,
            delta_micro_usdc=None,
            ready=False,
            blocked_reason="rpc_not_configured",
        )
    except BlockchainReadError:
        report = ProjectCapitalReconciliationReport(
            project_id=project.id,
            treasury_address=project.treasury_address,
            ledger_balance_micro_usdc=None,
            onchain_balance_micro_usdc=None,
            delta_micro_usdc=None,
            ready=False,
            blocked_reason="rpc_error",
        )
    else:
        delta = onchain.balance_micro_usdc - ledger_balance
        ready = delta == 0 and ledger_balance >= 0
        report = ProjectCapitalReconciliationReport(
            project_id=project.id,
            treasury_address=project.treasury_address,
            ledger_balance_micro_usdc=ledger_balance,
            onchain_balance_micro_usdc=onchain.balance_micro_usdc,
            delta_micro_usdc=delta,
            ready=ready,
            blocked_reason=None if ready else "balance_mismatch",
        )

    db.add(report)
    _record_oracle_audit(request, db, body_hash, request_id, idempotency_key, commit=False)
    db.commit()
    db.refresh(report)
    return ProjectCapitalReconciliationRunResponse(success=True, data=_recon_public(project_id, report))


def _validate_month(profit_month_id: str) -> None:
    if not _MONTH_RE.fullmatch(profit_month_id):
        raise HTTPException(status_code=400, detail="profit_month_id must use YYYYMM format")
    month = int(profit_month_id[4:6])
    if month < 1 or month > 12:
        raise HTTPException(status_code=400, detail="profit_month_id month must be 01..12")


def _generate_event_id(db: Session) -> str:
    for _ in range(5):
        candidate = f"pcap_{secrets.token_hex(8)}"
        if db.query(ProjectCapitalEvent).filter(ProjectCapitalEvent.event_id == candidate).first() is None:
            return candidate
    raise RuntimeError("Failed to generate unique event id.")


def _record_oracle_audit(
    request: Request,
    db: Session,
    body_hash: str,
    request_id: str,
    idempotency_key: str,
    error_hint: str | None = None,
    commit: bool = True,
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
        error_hint=error_hint,
        commit=commit,
    )


def _ensure_project_capital_outflow_reconciliation_gate(db: Session, project_db_id: int) -> str | None:
    latest = get_latest_project_capital_reconciliation(db, project_db_id)
    if latest is None:
        return "project_capital_reconciliation_missing"
    if not latest.ready or latest.delta_micro_usdc != 0:
        return "project_capital_not_reconciled"

    settings = get_settings()
    if not is_reconciliation_fresh(latest, settings.project_capital_reconciliation_max_age_seconds):
        return "project_capital_reconciliation_stale"
    return None


def _public(project_id: str, event: ProjectCapitalEvent) -> ProjectCapitalEventPublic:
    return ProjectCapitalEventPublic(
        event_id=event.event_id,
        idempotency_key=event.idempotency_key,
        profit_month_id=event.profit_month_id,
        project_id=project_id,
        delta_micro_usdc=event.delta_micro_usdc,
        source=event.source,
        evidence_tx_hash=event.evidence_tx_hash,
        evidence_url=event.evidence_url,
        created_at=event.created_at,
    )


def _recon_public(project_id: str, report: ProjectCapitalReconciliationReport) -> ProjectCapitalReconciliationReportPublic:
    return ProjectCapitalReconciliationReportPublic(
        project_id=project_id,
        treasury_address=report.treasury_address,
        ledger_balance_micro_usdc=report.ledger_balance_micro_usdc,
        onchain_balance_micro_usdc=report.onchain_balance_micro_usdc,
        delta_micro_usdc=report.delta_micro_usdc,
        ready=report.ready,
        blocked_reason=report.blocked_reason,
        computed_at=report.computed_at,
    )
