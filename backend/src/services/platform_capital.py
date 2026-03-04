from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import func
from sqlalchemy.orm import Session

from src.models.platform_capital_event import PlatformCapitalEvent
from src.models.platform_capital_reconciliation_report import PlatformCapitalReconciliationReport
from src.services.marketing_fee import get_platform_marketing_fee_reserve_micro_usdc


def get_platform_capital_balance_micro_usdc(db: Session) -> int:
    balance = db.query(func.coalesce(func.sum(PlatformCapitalEvent.delta_micro_usdc), 0)).scalar()
    return int(balance or 0)


def get_platform_capital_spendable_balance_micro_usdc(db: Session) -> int:
    gross = get_platform_capital_balance_micro_usdc(db)
    reserved = get_platform_marketing_fee_reserve_micro_usdc(db, bucket="platform_capital")
    return max(gross - reserved, 0)


def get_latest_platform_capital_reconciliation(
    db: Session,
) -> PlatformCapitalReconciliationReport | None:
    return (
        db.query(PlatformCapitalReconciliationReport)
        .order_by(
            PlatformCapitalReconciliationReport.computed_at.desc(),
            PlatformCapitalReconciliationReport.id.desc(),
        )
        .first()
    )


def is_reconciliation_fresh(
    reconciliation: PlatformCapitalReconciliationReport,
    max_age_seconds: int,
    *,
    now: datetime | None = None,
) -> bool:
    reference_now = now or datetime.now(timezone.utc)
    computed_at = reconciliation.computed_at
    if computed_at.tzinfo is None:
        computed_at = computed_at.replace(tzinfo=timezone.utc)
    return computed_at >= (reference_now - timedelta(seconds=max_age_seconds))
