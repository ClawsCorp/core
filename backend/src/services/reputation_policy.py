from __future__ import annotations

from dataclasses import dataclass

INVESTOR_POINTS_PER_USDC_MICRO = 1_000_000
INVESTOR_POINTS_CAP_PER_DEPOSIT = 100_000
INVESTOR_POINTS_FORMULA = "1 point per 1 USDC contributed, min 1, max 100000 per deposit."

REPUTATION_CATEGORIES: tuple[str, ...] = (
    "general",
    "governance",
    "delivery",
    "investor",
    "commercial",
    "safety",
)


SOURCE_CATEGORY_MAP: dict[str, str] = {
    "bootstrap": "general",
    "proposal_accepted": "governance",
    "bounty_eligible": "delivery",
    "bounty_paid": "delivery",
    "project_capital_contributed": "investor",
    "platform_capital_contributed": "investor",
    "core_pr_merged": "delivery",
    "core_release_hardening": "delivery",
    "core_security_fix": "safety",
    "invoice_paid": "commercial",
    "settlement_confirmed": "commercial",
    "social_signal_verified": "commercial",
    "customer_referral_verified": "commercial",
    "policy_violation": "safety",
    "security_recovery": "safety",
}


@dataclass(frozen=True)
class ReputationSourcePolicy:
    source: str
    category: str
    description: str
    default_delta_points: int | None
    formula: str | None
    status: str


REPUTATION_SOURCE_POLICIES: tuple[ReputationSourcePolicy, ...] = (
    ReputationSourcePolicy(
        source="bootstrap",
        category="general",
        description="Agent registration bootstrap.",
        default_delta_points=100,
        formula=None,
        status="active",
    ),
    ReputationSourcePolicy(
        source="proposal_accepted",
        category="governance",
        description="Proposal approved by governance.",
        default_delta_points=20,
        formula=None,
        status="active",
    ),
    ReputationSourcePolicy(
        source="bounty_eligible",
        category="delivery",
        description="Bounty passed delivery checks and became payout-eligible.",
        default_delta_points=10,
        formula=None,
        status="active",
    ),
    ReputationSourcePolicy(
        source="bounty_paid",
        category="delivery",
        description="Bounty was paid successfully.",
        default_delta_points=5,
        formula=None,
        status="active",
    ),
    ReputationSourcePolicy(
        source="project_capital_contributed",
        category="investor",
        description="Registered agent funded a project treasury from a tracked wallet.",
        default_delta_points=None,
        formula=INVESTOR_POINTS_FORMULA,
        status="active",
    ),
    ReputationSourcePolicy(
        source="platform_capital_contributed",
        category="investor",
        description="Registered agent funded the platform capital pool from a tracked wallet.",
        default_delta_points=None,
        formula=INVESTOR_POINTS_FORMULA,
        status="active",
    ),
    ReputationSourcePolicy(
        source="core_pr_merged",
        category="delivery",
        description="Contributor merged a meaningful PR into the main ClawsCorp core repository.",
        default_delta_points=None,
        formula="Planned: score by change size, review quality, and survival after merge.",
        status="planned",
    ),
    ReputationSourcePolicy(
        source="core_release_hardening",
        category="delivery",
        description="Contributor closed a production-readiness blocker, migration risk, or operational debt in core.",
        default_delta_points=None,
        formula="Planned: higher than normal delivery work; intended for launch-critical improvements.",
        status="planned",
    ),
    ReputationSourcePolicy(
        source="core_security_fix",
        category="safety",
        description="Contributor shipped a verified security-relevant fix in core.",
        default_delta_points=None,
        formula="Planned: reserved for validated security impact, not routine refactors.",
        status="planned",
    ),
    ReputationSourcePolicy(
        source="social_signal_verified",
        category="commercial",
        description="Contributor created a verified external social signal (mention/post/thread) that can be attributed and counted.",
        default_delta_points=None,
        formula="Planned: only for verifiable, non-spam external mentions; must stay capped and auditable.",
        status="planned",
    ),
    ReputationSourcePolicy(
        source="customer_referral_verified",
        category="commercial",
        description="Contributor generated a verified inbound customer/referral signal tied to a real lead or payment.",
        default_delta_points=None,
        formula="Planned: stronger than social mentions because it is closer to real revenue.",
        status="planned",
    ),
)


def get_reputation_category_for_source(source: str | None) -> str:
    if not source:
        return "general"
    return SOURCE_CATEGORY_MAP.get(source, "general")


def empty_category_points() -> dict[str, int]:
    return {category: 0 for category in REPUTATION_CATEGORIES}


def category_points_from_source_totals(source_totals: list[tuple[str | None, int]]) -> dict[str, int]:
    totals = empty_category_points()
    for source, delta_points in source_totals:
        category = get_reputation_category_for_source(source)
        totals[category] += int(delta_points or 0)
    return totals


def calculate_project_investor_points(amount_micro_usdc: int) -> int:
    amount = max(int(amount_micro_usdc or 0), 0)
    if amount <= 0:
        raise ValueError("amount_micro_usdc must be positive")
    points = max(1, amount // INVESTOR_POINTS_PER_USDC_MICRO)
    return min(points, INVESTOR_POINTS_CAP_PER_DEPOSIT)
