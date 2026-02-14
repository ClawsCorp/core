# Project Revenue (MVP)

Project revenue is a separate money bucket from project capital.

## Ledger definition (MVP)

- Inflows: `revenue_events` with `project_id=<project>`
- Outflows (MVP): `expense_events` with `project_id=<project>` and `category=project_bounty_payout_revenue`

Ledger balance (micro-USDC):

`SUM(revenue_events.amount_micro_usdc) - SUM(expense_events.amount_micro_usdc where category in revenue_outflow_categories)`

## On-chain anchor

- `projects.revenue_address` is the on-chain wallet that holds project revenue USDC.

## Reconciliation

Oracle endpoint:

- `POST /api/v1/oracle/projects/{project_id}/revenue/reconciliation`

Append-only reports:

- `project_revenue_reconciliation_reports`

## Fail-closed gate (bounty payouts)

When `bounties.funding_source = project_revenue`, `POST /api/v1/bounties/{bounty_id}/mark-paid` is blocked unless:

- latest revenue reconciliation exists
- it is strict-ready (`ready=true` and `delta_micro_usdc == 0`)
- it is fresh (`PROJECT_REVENUE_RECONCILIATION_MAX_AGE_SECONDS`)

Blocked reasons:

- `project_revenue_reconciliation_missing`
- `project_revenue_not_reconciled`
- `project_revenue_reconciliation_stale`
- `insufficient_project_revenue`

