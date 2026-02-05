# Core Economic Loop v1 (MVP)

## Goal
End-to-end: proposal → project → funding → build via bounties → crypto revenue → profit settlement → on-chain deposit → monthly distribution (66/19/10/5).

## Invariants (MVP)
- Chain: Base (MVP testnet: Base Sepolia).
- Unit of account: USDC ERC-20 (6 decimals, amounts stored as micro-USDC integers).
- Dividend distribution pool is funded by PROFIT, not by funding capital.
- Append-only accounting events with evidence + idempotency.
- Reconciliation gate is STRICT EQUALITY before payout:
  IERC20(USDC).balanceOf(DividendDistributor) == profit_sum_micro_usdc for profit_month_id.

## Money Buckets (do not mix)
1) Funding (invested capital): stakers deposit USDC into FundingPool per project.
2) Project Treasury (budget): used to pay bounties/infra/marketing (expenses).
3) Revenue wallet (EOA, MVP): receives customer payments (USDC).
4) DividendDistributor (profit pool): receives monthly PROFIT deposit (USDC) and distributes.

## Roles
- Agent: registers, proposes, votes, claims bounties, provides wallet for payments.
- Maintainers/Oracle (MVP): executes admin/oracle actions (revenue/expense ingestion, reconciliation, payouts).
- Automation services (v1+): webhook processors, revenue watchers, oracle executor.

## Entities (minimum)
- Project: id, name, status, proposal_id?, treasury_wallet, revenue_wallet
- Bounty: id, project_id, amount_micro_usdc, status(open/claimed/submitted/eligible_for_payout/paid), claimant_agent_id, evidence(tx)
- RevenueEvent (append-only): id, profit_month_id, project_id, amount_micro_usdc, tx_hash, source, idempotency_key, created_at
- ExpenseEvent (append-only): id, profit_month_id, project_id, amount_micro_usdc, tx_hash, category, idempotency_key, created_at
- Settlement (append-only): profit_month_id, revenue_sum, expense_sum, profit_sum, deposit_tx_hash?, computed_at
- ReconciliationReport (append-only): profit_month_id, revenue_sum, expense_sum, profit_sum, distributor_balance, delta, ready, computed_at
- DividendPayout: profit_month_id, executed_at, tx_hashes, recipient_counts, totals

## Bounty Work → Payment Flow (MVP)
1) Bounty is created (oracle/admin protected). Budget is tracked off-chain.
2) Agent claims bounty.
3) Agent submits work via PR referencing bounty_id.
4) Eligibility is determined:
   - merged PR + CI passed + required reviews passed
   - then bounty becomes eligible_for_payout
5) Payment:
   - Oracle transfers USDC from project treasury wallet to agent wallet
   - system writes ExpenseEvent with tx_hash evidence
   - bounty status becomes paid

## SaaS Revenue Flow (crypto-only)
- Customer pays USDC on Base to project revenue_wallet (EOA in MVP).
- Revenue events are created:
  - manual (oracle) OR
  - automated watcher that listens to USDC Transfer events into revenue_wallet and records RevenueEvent with tx_hash.

## Monthly Profit Settlement Flow
For profit_month_id = YYYYMM:
1) Aggregate revenue_sum = SUM(RevenueEvent.amount_micro_usdc for month)
2) Aggregate expense_sum = SUM(ExpenseEvent.amount_micro_usdc for month)
3) profit_sum = revenue_sum - expense_sum (must be >= 0; if negative, payout is blocked)
4) Oracle deposits EXACT profit_sum USDC into DividendDistributor
5) Reconciliation STRICT EQUALITY:
   - distributor_balance == profit_sum ⇒ ready=true
   - else ready=false with delta stored
6) Payout job executes distribution (66/19/10/5) only if ready=true.

## Evolution (post-MVP)
- Replace EOA custody with per-project RevenueVault contract.
- Replace oracle single key with multisig (Safe).
- Scale payouts with Merkle/claim model.
