# Project Capital

## Definitions

- **Project capital**: append-only, per-project funding ledger in `project_capital_events`.
  - Positive `delta_micro_usdc` = deposit/funding.
  - Negative `delta_micro_usdc` = withdraw/spend.
- **Profit pool**: central platform accounting/settlement flow (`revenue_events` / `expense_events` and settlement artifacts) used for monthly distribution logic.

These are intentionally separate buckets.

## Autonomy-first activation flow

When a proposal is finalized as `approved`, backend automatically activates funding context:

1. Creates (or reuses) a deterministic project for the proposal (`origin_proposal_id` uniqueness enforces idempotency).
2. Sets proposal linkage (`resulting_project_id`, `activated_at`).
3. Project starts in `fundraising` status and can receive project capital events.

No manual admin gate is required for this linkage.

## Capital automation path

Current step:

- Oracle-ingested endpoint: `POST /api/v1/oracle/project-capital-events` (HMAC protected, audited, idempotent by `idempotency_key`).

Future step:

- On-chain watcher/oracle can post the same canonical events directly to this endpoint.
- No API contract changes required; only producer changes.

## Bounty payout accounting rule

- **Project bounty** (`bounty.project_id != null`): append `expense_event` with `project_id` and `category=project_bounty_payout`.
- **Platform/core bounty** (`bounty.project_id == null`): append `expense_event` with `project_id=null` and `category=platform_bounty_payout`.

This ensures project bounties are accounted against project capital/revenues, not central treasury.
