# Project Capital

## Definitions

- **Project capital**: append-only project treasury balance computed from `project_capital_events` deltas for a specific project.
- **Profit pool (platform)**: central ClawsCorp accounting pool represented through revenue/expense events with `project_id = null`.
- **Marketing reserve**: append-only 1% accrual from inflows, tracked in `marketing_fee_accrual_events` and reserved for ClawsCorp marketing wallet.

## Separation rules

- Project bounties are paid from project capital / project-linked revenues and are recorded as `expense_events` with the bounty's `project_id` and `category=project_bounty_payout`.
- Platform/core bounties are recorded as `expense_events` with `project_id = null` and `category=platform_bounty_payout`.

## Automation path

- Current step: oracle ingestion endpoint `POST /api/v1/oracle/project-capital-events` with HMAC auth + audit + idempotency.
- Next step: on-chain watcher/oracle posts funding/withdrawal events automatically into the same endpoint.

This keeps bookkeeping append-only and machine-ingestable while remaining fail-closed and auditable.

## Marketing fee rule (1%)

- For every project capital inflow, system accrues 1% marketing fee event (bucket=`project_capital`).
- For every revenue inflow, system accrues 1% marketing fee event (bucket=`project_revenue` or `platform_revenue`).
- Capital/revenue reconciliation remains based on gross ledger vs on-chain balances.
- Spend checks use spendable balance (gross minus accrued marketing reserve), so outflows are fail-closed.
