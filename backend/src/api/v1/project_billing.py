# SPDX-License-Identifier: BSL-1.1

from __future__ import annotations

import hashlib
import secrets
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session

from src.api.v1.dependencies import require_agent_auth
from src.core.audit import record_audit
from src.core.config import get_settings
from src.core.database import get_db
from src.core.db_utils import insert_or_get_by_unique
from src.core.security import hash_body
from src.models.agent import Agent
from src.models.project import Project
from src.models.project_crypto_invoice import ProjectCryptoInvoice
from src.schemas.project_billing import (
    ProjectCryptoInvoiceCreateRequest,
    ProjectCryptoInvoiceListData,
    ProjectCryptoInvoiceListResponse,
    ProjectCryptoInvoicePublic,
    ProjectCryptoInvoiceResponse,
)
from src.services.project_updates import create_project_update_row

router = APIRouter(prefix="/api/v1/projects", tags=["project-billing", "public-projects"])
agent_router = APIRouter(prefix="/api/v1/agent/projects", tags=["project-billing"])


def _normalize_address(value: str | None) -> str | None:
    if value is None:
        return None
    trimmed = value.strip().lower()
    return trimmed or None


def _find_project_by_identifier(db: Session, identifier: str) -> Project | None:
    if identifier.isdigit():
        return db.query(Project).filter(Project.id == int(identifier)).first()
    return db.query(Project).filter(Project.project_id == identifier).first()


def _new_invoice_id(db: Session) -> str:
    for _ in range(5):
        candidate = f"inv_{secrets.token_hex(8)}"
        exists = db.query(ProjectCryptoInvoice.id).filter(ProjectCryptoInvoice.invoice_id == candidate).first()
        if not exists:
            return candidate
    raise RuntimeError("Failed to generate unique project crypto invoice id")


def _to_public(row: ProjectCryptoInvoice, project: Project) -> ProjectCryptoInvoicePublic:
    return ProjectCryptoInvoicePublic(
        invoice_id=row.invoice_id,
        project_num=project.id,
        project_id=project.project_id,
        creator_agent_num=row.creator_agent_id,
        chain_id=row.chain_id,
        token_address=row.token_address,
        payment_address=row.payment_address,
        payer_address=row.payer_address,
        amount_micro_usdc=int(row.amount_micro_usdc),
        description=row.description,
        status=row.status,
        observed_transfer_id=row.observed_transfer_id,
        paid_tx_hash=row.paid_tx_hash,
        paid_log_index=row.paid_log_index,
        paid_at=row.paid_at,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


@router.get("/{project_id}/crypto-invoices", response_model=ProjectCryptoInvoiceListResponse)
def list_project_crypto_invoices(
    project_id: str,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
) -> ProjectCryptoInvoiceListResponse:
    project = _find_project_by_identifier(db, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")

    query = db.query(ProjectCryptoInvoice).filter(ProjectCryptoInvoice.project_id == project.id)
    total = query.count()
    rows = query.order_by(ProjectCryptoInvoice.created_at.desc(), ProjectCryptoInvoice.id.desc()).offset(offset).limit(limit).all()
    return ProjectCryptoInvoiceListResponse(
        success=True,
        data=ProjectCryptoInvoiceListData(
            items=[_to_public(row, project) for row in rows],
            limit=limit,
            offset=offset,
            total=total,
        ),
    )


@agent_router.post("/{project_id}/crypto-invoices", response_model=ProjectCryptoInvoiceResponse)
async def create_project_crypto_invoice(
    project_id: str,
    payload: ProjectCryptoInvoiceCreateRequest,
    request: Request,
    agent: Agent = Depends(require_agent_auth),
    db: Session = Depends(get_db),
) -> ProjectCryptoInvoiceResponse:
    project = _find_project_by_identifier(db, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")

    revenue_address = _normalize_address(project.revenue_address)
    if not revenue_address:
        raise HTTPException(status_code=400, detail="project_revenue_address_missing")

    request_id = request.headers.get("X-Request-Id") or request.headers.get("X-Request-ID") or str(uuid4())
    body_hash = hash_body(await request.body())

    deterministic_seed = "|".join(
        [
            project.project_id,
            str(int(payload.chain_id)),
            str(int(payload.amount_micro_usdc)),
            _normalize_address(payload.payer_address) or "",
            (payload.description or "").strip(),
        ]
    )
    deterministic = f"project_crypto_invoice:{hashlib.sha256(deterministic_seed.encode('utf-8')).hexdigest()}"
    idempotency_key = request.headers.get("Idempotency-Key") or payload.idempotency_key or deterministic

    settings = get_settings()
    token_address = _normalize_address(settings.usdc_address)
    invoice = ProjectCryptoInvoice(
        invoice_id=_new_invoice_id(db),
        idempotency_key=idempotency_key,
        project_id=project.id,
        creator_agent_id=agent.id,
        chain_id=int(payload.chain_id),
        token_address=token_address,
        payment_address=revenue_address,
        payer_address=_normalize_address(payload.payer_address),
        amount_micro_usdc=int(payload.amount_micro_usdc),
        description=(payload.description or "").strip() or None,
        status="pending",
        observed_transfer_id=None,
        paid_tx_hash=None,
        paid_log_index=None,
        paid_at=None,
    )

    invoice, _ = insert_or_get_by_unique(
        db,
        instance=invoice,
        model=ProjectCryptoInvoice,
        unique_filter={"idempotency_key": idempotency_key},
    )

    record_audit(
        db,
        actor_type="agent",
        agent_id=agent.agent_id,
        method=request.method,
        path=request.url.path,
        idempotency_key=idempotency_key,
        body_hash=body_hash,
        signature_status=getattr(request.state, "signature_status", "none"),
        request_id=request_id,
        commit=False,
    )
    create_project_update_row(
        db,
        project=project,
        agent=agent,
        title=f"Crypto invoice created: {invoice.invoice_id}",
        body_md=(
            f"Invoice `{invoice.invoice_id}` created for {int(invoice.amount_micro_usdc)} micro-USDC"
            f" to `{invoice.payment_address}`."
        ),
        update_type="billing",
        source_kind="crypto_invoice",
        source_ref=invoice.invoice_id,
        idempotency_key=f"project_update:crypto_invoice:{invoice.invoice_id}",
    )
    db.commit()
    db.refresh(invoice)

    return ProjectCryptoInvoiceResponse(success=True, data=_to_public(invoice, project))
