from __future__ import annotations

import hashlib
import secrets

from sqlalchemy import func
from sqlalchemy.orm import Session

from src.core.config import get_settings
from src.core.db_utils import insert_or_get_by_unique
from src.models.marketing_fee_accrual_event import MarketingFeeAccrualEvent

MAX_MARKETING_IDEMPOTENCY_KEY_LEN = 255


def build_marketing_fee_idempotency_key(*, prefix: str, source_idempotency_key: str) -> str:
    raw = f"{prefix}:{source_idempotency_key}"
    if len(raw) <= MAX_MARKETING_IDEMPOTENCY_KEY_LEN:
        return raw

    digest = hashlib.sha256(source_idempotency_key.encode("utf-8")).hexdigest()
    suffix = f"sha256:{digest}"
    max_prefix_len = MAX_MARKETING_IDEMPOTENCY_KEY_LEN - len(suffix) - 1
    safe_prefix = prefix[: max(0, max_prefix_len)]
    return f"{safe_prefix}:{suffix}"


def calculate_marketing_fee_micro_usdc(amount_micro_usdc: int, fee_bps: int | None = None) -> int:
    bps = int(fee_bps if fee_bps is not None else get_settings().marketing_fee_bps)
    if amount_micro_usdc <= 0 or bps <= 0:
        return 0
    return max((int(amount_micro_usdc) * bps) // 10_000, 0)


def accrue_marketing_fee_event(
    db: Session,
    *,
    idempotency_key: str,
    project_id: int | None,
    profit_month_id: str | None,
    bucket: str,
    source: str,
    gross_amount_micro_usdc: int,
    chain_id: int | None,
    tx_hash: str | None,
    log_index: int | None,
    evidence_url: str | None,
) -> tuple[MarketingFeeAccrualEvent | None, bool, int]:
    fee_amount = calculate_marketing_fee_micro_usdc(int(gross_amount_micro_usdc))
    if fee_amount <= 0:
        return None, False, 0

    event = MarketingFeeAccrualEvent(
        event_id=_generate_event_id(db),
        idempotency_key=idempotency_key,
        project_id=project_id,
        profit_month_id=profit_month_id,
        bucket=bucket,
        source=source,
        gross_amount_micro_usdc=int(gross_amount_micro_usdc),
        fee_amount_micro_usdc=fee_amount,
        chain_id=chain_id,
        tx_hash=tx_hash,
        log_index=log_index,
        evidence_url=evidence_url,
    )
    row, created = insert_or_get_by_unique(
        db,
        instance=event,
        model=MarketingFeeAccrualEvent,
        unique_filter={"idempotency_key": idempotency_key},
    )
    return row, created, int(row.fee_amount_micro_usdc)


def get_project_marketing_fee_reserve_micro_usdc(db: Session, project_id: int, *, bucket: str) -> int:
    total = (
        db.query(func.coalesce(func.sum(MarketingFeeAccrualEvent.fee_amount_micro_usdc), 0))
        .filter(
            MarketingFeeAccrualEvent.project_id == int(project_id),
            MarketingFeeAccrualEvent.bucket == bucket,
        )
        .scalar()
    )
    return int(total or 0)


def get_total_marketing_fee_accrued_micro_usdc(db: Session) -> int:
    total = db.query(func.coalesce(func.sum(MarketingFeeAccrualEvent.fee_amount_micro_usdc), 0)).scalar()
    return int(total or 0)


def _generate_event_id(db: Session) -> str:
    for _ in range(5):
        candidate = f"mfee_{secrets.token_hex(8)}"
        exists = db.query(MarketingFeeAccrualEvent.id).filter(MarketingFeeAccrualEvent.event_id == candidate).first()
        if not exists:
            return candidate
    raise RuntimeError("Failed to generate unique marketing fee accrual event id")
