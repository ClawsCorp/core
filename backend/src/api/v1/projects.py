from __future__ import annotations

import re
import secrets
from datetime import datetime, timezone
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from sqlalchemy import case, desc, func
from sqlalchemy.orm import Session

from src.api.v1.dependencies import require_oracle_hmac
from src.core.audit import record_audit
from src.core.database import get_db
from src.models.agent import Agent
from src.models.project import Project, ProjectStatus
from src.models.project_capital_event import ProjectCapitalEvent
from src.models.project_capital_reconciliation_report import ProjectCapitalReconciliationReport
from src.models.project_funding_deposit import ProjectFundingDeposit
from src.models.project_funding_round import ProjectFundingRound
from src.models.project_revenue_reconciliation_report import ProjectRevenueReconciliationReport
from src.models.project_member import ProjectMember
from src.schemas.project_funding import (
    ProjectFundingContributor,
    ProjectFundingRoundPublic,
    ProjectFundingSummary,
    ProjectFundingSummaryResponse,
)
from src.schemas.project import (
    ProjectCapitalLeaderboardData,
    ProjectCapitalLeaderboardResponse,
    ProjectCapitalReconciliationLatestResponse,
    ProjectCapitalReconciliationReportPublic,
    ProjectRevenueReconciliationLatestResponse,
    ProjectRevenueReconciliationReportPublic,
    ProjectCapitalSummary,
    ProjectCapitalSummaryResponse,
    ProjectCreateRequest,
    ProjectDetail,
    ProjectDetailResponse,
    ProjectListData,
    ProjectListResponse,
    ProjectMemberInfo,
    ProjectMemberRole,
    ProjectStatus as ProjectStatusSchema,
    ProjectStatusUpdateRequest,
    ProjectSummary,
)

router = APIRouter(prefix="/api/v1/projects", tags=["public-projects", "projects"])


@router.get("/capital/leaderboard", response_model=ProjectCapitalLeaderboardResponse, summary="Project capital leaderboard")
def project_capital_leaderboard(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
) -> ProjectCapitalLeaderboardResponse:
    base = db.query(
        Project.project_id.label("project_id"),
        func.coalesce(func.sum(ProjectCapitalEvent.delta_micro_usdc), 0).label("capital_sum_micro_usdc"),
        func.count(ProjectCapitalEvent.id).label("events_count"),
        func.max(ProjectCapitalEvent.created_at).label("last_event_at"),
    ).join(ProjectCapitalEvent, ProjectCapitalEvent.project_id == Project.id).group_by(Project.id)

    total = base.count()
    rows = base.order_by(desc("capital_sum_micro_usdc"), Project.project_id.asc()).offset(offset).limit(limit).all()
    items = [
        ProjectCapitalSummary(
            project_id=row.project_id,
            balance_micro_usdc=int(row.capital_sum_micro_usdc or 0),
            capital_sum_micro_usdc=int(row.capital_sum_micro_usdc or 0),
            events_count=int(row.events_count or 0),
            last_event_at=row.last_event_at,
        )
        for row in rows
    ]
    return ProjectCapitalLeaderboardResponse(success=True, data=ProjectCapitalLeaderboardData(items=items, limit=limit, offset=offset, total=total))


@router.get(
    "",
    response_model=ProjectListResponse,
    summary="List projects",
    description="Public read endpoint for portal project list.",
)
def list_projects(
    response: Response,
    status: ProjectStatusSchema | None = Query(None),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
) -> ProjectListResponse:
    query = db.query(Project)
    if status is not None:
        query = query.filter(Project.status == ProjectStatus(status))
    total = query.count()
    projects = query.order_by(Project.created_at.desc()).offset(offset).limit(limit).all()
    items = [_project_summary(project) for project in projects]
    page_max_updated_at = 0
    if projects:
        page_max_updated_at = max(int(project.updated_at.timestamp()) for project in projects)
    result = ProjectListResponse(
        success=True,
        data=ProjectListData(items=items, limit=limit, offset=offset, total=total),
    )
    response.headers["Cache-Control"] = "public, max-age=60"
    response.headers["ETag"] = f'W/"projects:{status or "all"}:{offset}:{limit}:{total}:{page_max_updated_at}"'
    return result


@router.get(
    "/slug/{slug}",
    response_model=ProjectDetailResponse,
    summary="Get project detail by slug",
    description="Public read endpoint for a project and public member roster by project slug.",
)
def get_project_by_slug(
    slug: str,
    response: Response,
    db: Session = Depends(get_db),
) -> ProjectDetailResponse:
    project = db.query(Project).filter(Project.slug == slug).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    detail = _project_detail(db, project)
    result = ProjectDetailResponse(success=True, data=detail)
    response.headers["Cache-Control"] = "public, max-age=60"
    cap_recon_ts = 0
    if detail.capital_reconciliation is not None:
        cap_recon_ts = int(detail.capital_reconciliation.computed_at.timestamp())
    response.headers["ETag"] = f'W/"project-slug:{project.slug}:{int(project.updated_at.timestamp())}:{cap_recon_ts}"'
    return result


@router.get("/{project_id}/capital", response_model=ProjectCapitalSummaryResponse, summary="Get project capital summary")
def get_project_capital(project_id: str, db: Session = Depends(get_db)) -> ProjectCapitalSummaryResponse:
    project = db.query(Project).filter(Project.project_id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    row = db.query(
        func.coalesce(func.sum(ProjectCapitalEvent.delta_micro_usdc), 0),
        func.count(ProjectCapitalEvent.id),
        func.max(ProjectCapitalEvent.created_at),
    ).filter(ProjectCapitalEvent.project_id == project.id).one()

    return ProjectCapitalSummaryResponse(
        success=True,
        data=ProjectCapitalSummary(
            project_id=project.project_id,
            balance_micro_usdc=int(row[0] or 0),
            capital_sum_micro_usdc=int(row[0] or 0),
            events_count=int(row[1] or 0),
            last_event_at=row[2],
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


@router.get("/{project_id}/funding", response_model=ProjectFundingSummaryResponse, summary="Get project funding summary")
def get_project_funding_summary(project_id: str, db: Session = Depends(get_db)) -> ProjectFundingSummaryResponse:
    project = db.query(Project).filter(Project.project_id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    open_round = (
        db.query(ProjectFundingRound)
        .filter(ProjectFundingRound.project_id == project.id, ProjectFundingRound.status == "open")
        .order_by(ProjectFundingRound.opened_at.desc(), ProjectFundingRound.id.desc())
        .first()
    )

    open_round_raised_observed = 0
    if open_round is not None:
        open_round_raised_observed = int(
            db.query(func.coalesce(func.sum(ProjectFundingDeposit.amount_micro_usdc), 0))
            .filter(ProjectFundingDeposit.project_id == project.id, ProjectFundingDeposit.funding_round_id == open_round.id)
            .scalar()
            or 0
        )

    total_raised_observed = int(
        db.query(func.coalesce(func.sum(ProjectFundingDeposit.amount_micro_usdc), 0))
        .filter(ProjectFundingDeposit.project_id == project.id)
        .scalar()
        or 0
    )

    # Indexer lag fallback:
    # derive inflow totals from append-only capital events so funding summary remains truthful
    # even when observed transfer ingestion is temporarily stale.
    inflow_case = case((ProjectCapitalEvent.delta_micro_usdc > 0, ProjectCapitalEvent.delta_micro_usdc), else_=0)
    total_inflow_ledger = int(
        db.query(func.coalesce(func.sum(inflow_case), 0))
        .filter(ProjectCapitalEvent.project_id == project.id)
        .scalar()
        or 0
    )
    open_round_inflow_ledger = 0
    if open_round is not None:
        open_round_inflow_query = (
            db.query(func.coalesce(func.sum(inflow_case), 0))
            .filter(
                ProjectCapitalEvent.project_id == project.id,
                ProjectCapitalEvent.created_at >= open_round.opened_at,
            )
        )
        if open_round.closed_at is not None:
            open_round_inflow_query = open_round_inflow_query.filter(ProjectCapitalEvent.created_at <= open_round.closed_at)
        open_round_inflow_ledger = int(open_round_inflow_query.scalar() or 0)

    contributors_rows = (
        db.query(
            ProjectFundingDeposit.from_address,
            func.coalesce(func.sum(ProjectFundingDeposit.amount_micro_usdc), 0).label("amount_micro_usdc"),
        )
        .filter(
            ProjectFundingDeposit.project_id == project.id,
            ProjectFundingDeposit.funding_round_id == (open_round.id if open_round is not None else None),
        )
        .group_by(ProjectFundingDeposit.from_address)
        .order_by(desc("amount_micro_usdc"), ProjectFundingDeposit.from_address.asc())
        .limit(20)
        .all()
        if open_round is not None
        else []
    )
    contributors = [
        ProjectFundingContributor(address=str(addr), amount_micro_usdc=int(amount or 0))
        for addr, amount in contributors_rows
    ]

    contributors_total_count = 0
    if open_round is not None:
        contributors_total_count = int(
            db.query(func.count(func.distinct(ProjectFundingDeposit.from_address)))
            .filter(ProjectFundingDeposit.project_id == project.id, ProjectFundingDeposit.funding_round_id == open_round.id)
            .scalar()
            or 0
        )

    total_raised = total_raised_observed
    open_round_raised = open_round_raised_observed
    contributors_data_source = "observed_transfers"
    unattributed_micro_usdc = 0
    if total_inflow_ledger > total_raised_observed:
        total_raised = total_inflow_ledger
        if open_round is not None:
            open_round_raised = max(open_round_raised_observed, open_round_inflow_ledger, total_inflow_ledger)
        else:
            open_round_raised = max(open_round_raised_observed, open_round_inflow_ledger)
        contributors_data_source = "mixed_with_ledger_fallback" if total_raised_observed > 0 else "ledger_fallback"
        unattributed_micro_usdc = int(total_inflow_ledger - total_raised_observed)

    last_deposit_at = (
        db.query(func.max(ProjectFundingDeposit.observed_at))
        .filter(ProjectFundingDeposit.project_id == project.id)
        .scalar()
    )

    return ProjectFundingSummaryResponse(
        success=True,
        data=ProjectFundingSummary(
            project_id=project.project_id,
            open_round=_funding_round_public(project.project_id, open_round) if open_round is not None else None,
            open_round_raised_micro_usdc=open_round_raised,
            total_raised_micro_usdc=total_raised,
            contributors=contributors,
            contributors_total_count=contributors_total_count,
            contributors_data_source=contributors_data_source,
            unattributed_micro_usdc=unattributed_micro_usdc,
            last_deposit_at=last_deposit_at,
        ),
    )


@router.get(
    "/{project_id}/capital/reconciliation/latest",
    response_model=ProjectCapitalReconciliationLatestResponse,
    summary="Get latest project capital reconciliation report",
)
def get_project_capital_reconciliation_latest(
    project_id: str,
    db: Session = Depends(get_db),
) -> ProjectCapitalReconciliationLatestResponse:
    project = db.query(Project).filter(Project.project_id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    report = (
        db.query(ProjectCapitalReconciliationReport)
        .filter(ProjectCapitalReconciliationReport.project_id == project.id)
        .order_by(ProjectCapitalReconciliationReport.computed_at.desc())
        .first()
    )
    return ProjectCapitalReconciliationLatestResponse(success=True, data=_reconciliation_public(project.project_id, report))


@router.get(
    "/{project_id}/revenue/reconciliation/latest",
    response_model=ProjectRevenueReconciliationLatestResponse,
    summary="Get latest project revenue reconciliation report",
)
def get_project_revenue_reconciliation_latest(
    project_id: str,
    db: Session = Depends(get_db),
) -> ProjectRevenueReconciliationLatestResponse:
    project = db.query(Project).filter(Project.project_id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    report = (
        db.query(ProjectRevenueReconciliationReport)
        .filter(ProjectRevenueReconciliationReport.project_id == project.id)
        .order_by(ProjectRevenueReconciliationReport.computed_at.desc())
        .first()
    )
    return ProjectRevenueReconciliationLatestResponse(success=True, data=_revenue_reconciliation_public(project.project_id, report))


@router.get(
    "/{project_id}",
    response_model=ProjectDetailResponse,
    summary="Get project detail",
    description="Public read endpoint for a project and public member roster.",
)
def get_project(
    project_id: str,
    response: Response,
    db: Session = Depends(get_db),
) -> ProjectDetailResponse:
    project = db.query(Project).filter(Project.project_id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    detail = _project_detail(db, project)
    result = ProjectDetailResponse(success=True, data=detail)
    response.headers["Cache-Control"] = "public, max-age=60"
    cap_recon_ts = 0
    if detail.capital_reconciliation is not None:
        cap_recon_ts = int(detail.capital_reconciliation.computed_at.timestamp())
    response.headers["ETag"] = f'W/"project:{project.project_id}:{int(project.updated_at.timestamp())}:{cap_recon_ts}"'
    return result


@router.post("", response_model=ProjectDetailResponse)
async def create_project(
    payload: ProjectCreateRequest,
    request: Request,
    _: str = Depends(require_oracle_hmac),
    db: Session = Depends(get_db),
) -> ProjectDetailResponse:
    request_id = request.headers.get("X-Request-Id") or request.headers.get("X-Request-ID") or str(uuid4())
    idempotency_key = request.headers.get("Idempotency-Key")
    body_hash = request.state.body_hash

    project_id = _generate_project_id(db)
    project = Project(
        project_id=project_id,
        slug=_generate_project_slug(db, payload.name, project_id),
        name=payload.name,
        description_md=payload.description_md,
        status=ProjectStatus.draft,
        proposal_id=payload.proposal_id,
        treasury_wallet_address=payload.treasury_wallet_address,
        revenue_wallet_address=payload.revenue_wallet_address,
        revenue_address=(payload.revenue_address.strip().lower() if payload.revenue_address else None),
        monthly_budget_micro_usdc=payload.monthly_budget_micro_usdc,
    )
    db.add(project)
    db.commit()
    db.refresh(project)

    _record_oracle_audit(request, db, body_hash, request_id, idempotency_key)

    return ProjectDetailResponse(success=True, data=_project_detail(db, project))


@router.post("/{project_id}/approve", response_model=ProjectDetailResponse)
async def approve_project(
    project_id: str,
    request: Request,
    _: str = Depends(require_oracle_hmac),
    db: Session = Depends(get_db),
) -> ProjectDetailResponse:
    request_id = request.headers.get("X-Request-Id") or request.headers.get("X-Request-ID") or str(uuid4())
    idempotency_key = request.headers.get("Idempotency-Key")
    body_hash = request.state.body_hash

    project = db.query(Project).filter(Project.project_id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    if project.status == ProjectStatus.archived:
        raise HTTPException(status_code=400, detail="Archived projects are terminal.")

    project.status = ProjectStatus.active
    if project.approved_at is None:
        project.approved_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(project)

    _record_oracle_audit(request, db, body_hash, request_id, idempotency_key)

    return ProjectDetailResponse(success=True, data=_project_detail(db, project))


@router.post("/{project_id}/status", response_model=ProjectDetailResponse)
async def update_project_status(
    project_id: str,
    payload: ProjectStatusUpdateRequest,
    request: Request,
    _: str = Depends(require_oracle_hmac),
    db: Session = Depends(get_db),
) -> ProjectDetailResponse:
    request_id = request.headers.get("X-Request-Id") or request.headers.get("X-Request-ID") or str(uuid4())
    idempotency_key = request.headers.get("Idempotency-Key")
    body_hash = request.state.body_hash

    project = db.query(Project).filter(Project.project_id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    if project.status == ProjectStatus.archived and payload.status != ProjectStatus.archived:
        raise HTTPException(status_code=400, detail="Archived projects are terminal.")

    project.status = ProjectStatus(payload.status)
    if project.status == ProjectStatus.active and project.approved_at is None:
        project.approved_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(project)

    _record_oracle_audit(request, db, body_hash, request_id, idempotency_key)

    return ProjectDetailResponse(success=True, data=_project_detail(db, project))


def _record_oracle_audit(
    request: Request,
    db: Session,
    body_hash: str,
    request_id: str,
    idempotency_key: str | None,
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
    )


def _generate_project_id(db: Session) -> str:
    for _ in range(5):
        candidate = f"proj_{secrets.token_hex(8)}"
        exists = db.query(Project).filter(Project.project_id == candidate).first()
        if not exists:
            return candidate
    raise RuntimeError("Failed to generate unique project id.")


def _generate_project_slug(db: Session, name: str, project_id: str) -> str:
    base = _slugify_name(name)
    candidates = [base, f"{base}-{project_id[-6:]}", f"proj-{project_id}"]

    for candidate in candidates:
        if not db.query(Project).filter(Project.slug == candidate).first():
            return candidate

    for _ in range(5):
        fallback = f"{base}-{secrets.token_hex(2)}"
        if not db.query(Project).filter(Project.slug == fallback).first():
            return fallback

    return f"proj-{project_id}"


def _slugify_name(name: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return (normalized or "project")[:48].strip("-") or "project"


def _project_summary(project: Project) -> ProjectSummary:
    return ProjectSummary(
        project_id=project.project_id,
        slug=project.slug,
        name=project.name,
        description_md=project.description_md,
        status=ProjectStatusSchema(project.status),
        proposal_id=project.proposal_id,
        origin_proposal_id=project.origin_proposal_id,
        originator_agent_id=project.originator_agent_id,
        discussion_thread_id=project.discussion_thread_id,
        treasury_wallet_address=project.treasury_wallet_address,
        treasury_address=project.treasury_address,
        revenue_wallet_address=project.revenue_wallet_address,
        revenue_address=project.revenue_address,
        monthly_budget_micro_usdc=project.monthly_budget_micro_usdc,
        created_at=project.created_at,
        updated_at=project.updated_at,
        approved_at=project.approved_at,
    )


def _project_detail(db: Session, project: Project) -> ProjectDetail:
    members = _load_project_members(db, project.id)
    latest_report = (
        db.query(ProjectCapitalReconciliationReport)
        .filter(ProjectCapitalReconciliationReport.project_id == project.id)
        .order_by(ProjectCapitalReconciliationReport.computed_at.desc())
        .first()
    )
    latest_revenue_report = (
        db.query(ProjectRevenueReconciliationReport)
        .filter(ProjectRevenueReconciliationReport.project_id == project.id)
        .order_by(ProjectRevenueReconciliationReport.computed_at.desc())
        .first()
    )
    return ProjectDetail(
        **_project_summary(project).model_dump(),
        members=members,
        capital_reconciliation=_reconciliation_public(project.project_id, latest_report),
        revenue_reconciliation=_revenue_reconciliation_public(project.project_id, latest_revenue_report),
    )


def _reconciliation_public(
    project_id: str,
    report: ProjectCapitalReconciliationReport | None,
) -> ProjectCapitalReconciliationReportPublic | None:
    if report is None:
        return None
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


def _revenue_reconciliation_public(
    project_id: str,
    report: ProjectRevenueReconciliationReport | None,
) -> ProjectRevenueReconciliationReportPublic | None:
    if report is None:
        return None
    return ProjectRevenueReconciliationReportPublic(
        project_id=project_id,
        revenue_address=report.revenue_address,
        ledger_balance_micro_usdc=report.ledger_balance_micro_usdc,
        onchain_balance_micro_usdc=report.onchain_balance_micro_usdc,
        delta_micro_usdc=report.delta_micro_usdc,
        ready=report.ready,
        blocked_reason=report.blocked_reason,
        computed_at=report.computed_at,
    )


def _load_project_members(db: Session, project_pk: int) -> list[ProjectMemberInfo]:
    rows = (
        db.query(Agent.agent_id, Agent.name, ProjectMember.role)
        .join(ProjectMember, ProjectMember.agent_id == Agent.id)
        .filter(ProjectMember.project_id == project_pk)
        .order_by(Agent.agent_id)
        .all()
    )
    return [
        ProjectMemberInfo(
            agent_id=row.agent_id,
            name=row.name,
            role=ProjectMemberRole(row.role),
        )
        for row in rows
    ]
