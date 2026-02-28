from __future__ import annotations

import secrets
from datetime import timezone
from uuid import uuid4

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from src.api.v1.dependencies import require_oracle_hmac
from src.core.audit import record_audit
from src.core.database import get_db
from src.core.db_utils import insert_or_get_by_unique
from src.models.billing_event import BillingEvent
from src.models.observed_usdc_transfer import ObservedUsdcTransfer
from src.models.project import Project
from src.models.project_crypto_invoice import ProjectCryptoInvoice
from src.models.revenue_event import RevenueEvent
from src.services.marketing_fee import accrue_marketing_fee_event
from src.services.blockchain import BlockchainReadError, read_block_timestamp_utc
from src.services.project_updates import create_project_update_row
from src.schemas.billing import BillingSyncResponse

router = APIRouter(prefix="/api/v1/oracle", tags=["oracle-billing"])


def _generate_event_id(db: Session) -> str:
    for _ in range(5):
        candidate = f"rev_{secrets.token_hex(8)}"
        exists = db.query(RevenueEvent.id).filter(RevenueEvent.event_id == candidate).first()
        if not exists:
            return candidate
    raise RuntimeError("Failed to generate unique revenue event id")


@router.post("/billing/sync", response_model=BillingSyncResponse)
async def sync_billing(
    request: Request,
    _: str = Depends(require_oracle_hmac),
    db: Session = Depends(get_db),
) -> BillingSyncResponse:
    """
    MVP billing ingestion: on-chain USDC transfers into `projects.revenue_address` become append-only billing_events and revenue_events.

    Oracle remains a fallback; this endpoint is an autonomous helper for real commerce flows.
    """
    request_id = request.headers.get("X-Request-Id") or request.headers.get("X-Request-ID") or str(uuid4())
    body_hash = getattr(request.state, "body_hash", "")

    projects = db.query(Project).filter(Project.revenue_address.isnot(None)).all()
    addr_to_project: dict[str, Project] = {}
    for project in projects:
        if project.revenue_address:
            addr_to_project[str(project.revenue_address).lower()] = project

    if not addr_to_project:
        record_audit(
            db,
            actor_type="oracle",
            agent_id=None,
            method=request.method,
            path=request.url.path,
            idempotency_key=request.headers.get("Idempotency-Key"),
            body_hash=body_hash,
            signature_status=getattr(request.state, "signature_status", "invalid"),
            request_id=request_id,
            commit=True,
        )
        return BillingSyncResponse(
            success=True,
            data={
                "billing_events_inserted": 0,
                "revenue_events_inserted": 0,
                "marketing_fee_events_inserted": 0,
                "marketing_fee_total_micro_usdc": 0,
                "invoices_paid": 0,
            },
        )

    # Process newest first to keep UI current; idempotency protects duplicates.
    transfers = (
        db.query(ObservedUsdcTransfer)
        .filter(ObservedUsdcTransfer.to_address.in_(list(addr_to_project.keys())))
        .order_by(ObservedUsdcTransfer.block_number.desc(), ObservedUsdcTransfer.log_index.desc())
        .limit(500)
        .all()
    )

    billing_inserted = 0
    revenue_inserted = 0
    marketing_fee_events_inserted = 0
    marketing_fee_total_micro_usdc = 0
    invoices_paid = 0
    block_ts_cache: dict[int, str] = {}

    for t in transfers:
        dest = str(t.to_address).lower()
        if dest not in addr_to_project:
            continue
        project_row = addr_to_project[dest]
        project_db_id = int(project_row.id)
        project_public_id = str(project_row.project_id)

        # Best-effort block timestamp (cache per block). If it fails, fall back to observed_at.
        profit_month_id: str
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

        billing = BillingEvent(
            chain_id=int(t.chain_id),
            tx_hash=str(t.tx_hash),
            log_index=int(t.log_index),
            block_number=int(t.block_number),
            from_address=str(t.from_address),
            to_address=str(t.to_address),
            amount_micro_usdc=int(t.amount_micro_usdc),
            project_id=project_db_id,
            kind="project_revenue",
            observed_at=t.observed_at,
        )
        _, created = insert_or_get_by_unique(
            db,
            instance=billing,
            model=BillingEvent,
            unique_filter={"chain_id": int(t.chain_id), "tx_hash": str(t.tx_hash), "log_index": int(t.log_index)},
        )
        if created:
            billing_inserted += 1

        rev_idem = f"rev:billing:{int(t.chain_id)}:{t.tx_hash}:{int(t.log_index)}"
        revenue = RevenueEvent(
            event_id=_generate_event_id(db),
            profit_month_id=profit_month_id,
            project_id=project_db_id,
            amount_micro_usdc=int(t.amount_micro_usdc),
            tx_hash=str(t.tx_hash),
            source="customer_billing_usdc_transfer",
            idempotency_key=rev_idem,
            evidence_url=f"usdc_transfer:{t.tx_hash}#log:{int(t.log_index)};to:{project_public_id}",
        )
        _rev_row, rev_created = insert_or_get_by_unique(
            db,
            instance=revenue,
            model=RevenueEvent,
            unique_filter={"idempotency_key": rev_idem},
        )
        if rev_created:
            revenue_inserted += 1

        _mfee_row, mfee_created, mfee_amount = accrue_marketing_fee_event(
            db,
            idempotency_key=f"mfee:billing:{int(t.chain_id)}:{str(t.tx_hash).lower()}:{int(t.log_index)}:to:{project_public_id}",
            project_id=project_db_id,
            profit_month_id=profit_month_id,
            bucket="project_revenue",
            source="customer_billing_usdc_transfer",
            gross_amount_micro_usdc=int(t.amount_micro_usdc),
            chain_id=int(t.chain_id),
            tx_hash=str(t.tx_hash).lower(),
            log_index=int(t.log_index),
            evidence_url=f"usdc_transfer:{t.tx_hash}#log:{int(t.log_index)};to:{project_public_id}",
        )
        if mfee_created:
            marketing_fee_events_inserted += 1
        marketing_fee_total_micro_usdc += int(mfee_amount)

        # Crypto billing reconciliation:
        # mark the oldest matching pending invoice as paid (same project/address/amount/chain),
        # and respect optional payer filter if set by the project.
        invoice_query = (
            db.query(ProjectCryptoInvoice)
            .filter(
                ProjectCryptoInvoice.project_id == project_db_id,
                ProjectCryptoInvoice.status == "pending",
                ProjectCryptoInvoice.chain_id == int(t.chain_id),
                ProjectCryptoInvoice.payment_address == dest,
                ProjectCryptoInvoice.amount_micro_usdc == int(t.amount_micro_usdc),
            )
            .order_by(ProjectCryptoInvoice.created_at.asc(), ProjectCryptoInvoice.id.asc())
        )
        from_addr = str(t.from_address).lower()
        invoice_query = invoice_query.filter(
            (ProjectCryptoInvoice.payer_address.is_(None)) | (ProjectCryptoInvoice.payer_address == from_addr)
        )
        invoice = invoice_query.first()
        if invoice is not None:
            invoice.status = "paid"
            invoice.observed_transfer_id = int(t.id)
            invoice.paid_tx_hash = str(t.tx_hash)
            invoice.paid_log_index = int(t.log_index)
            invoice.paid_at = t.observed_at
            db.add(invoice)
            create_project_update_row(
                db,
                project=project_row,
                agent=None,
                title=f"Invoice paid: {invoice.invoice_id}",
                body_md=(
                    f"Invoice `{invoice.invoice_id}` was paid via `{t.tx_hash}`"
                    f" for {int(t.amount_micro_usdc)} micro-USDC."
                ),
                update_type="revenue",
                source_kind="crypto_invoice_paid",
                source_ref=invoice.invoice_id,
                idempotency_key=f"project_update:crypto_invoice_paid:{invoice.invoice_id}",
            )
            invoices_paid += 1

    record_audit(
        db,
        actor_type="oracle",
        agent_id=None,
        method=request.method,
        path=request.url.path,
        idempotency_key=request.headers.get("Idempotency-Key"),
        body_hash=body_hash,
        signature_status=getattr(request.state, "signature_status", "invalid"),
        request_id=request_id,
        commit=False,
    )
    db.commit()
    return BillingSyncResponse(
        success=True,
        data={
            "billing_events_inserted": billing_inserted,
            "revenue_events_inserted": revenue_inserted,
            "marketing_fee_events_inserted": marketing_fee_events_inserted,
            "marketing_fee_total_micro_usdc": marketing_fee_total_micro_usdc,
            "invoices_paid": invoices_paid,
        },
    )
