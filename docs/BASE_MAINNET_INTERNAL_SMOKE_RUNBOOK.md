# Base Mainnet Internal Financial Smoke Runbook

Purpose: execute the first tightly controlled real-money smoke loop on Base mainnet after:

- contracts are already deployed
- ownership is already on the mainnet Safe
- live environment is already switched to the mainnet configuration

This runbook is the last internal validation step before any external-agent public launch.

## Goal

Prove that the system can complete a minimal real-money operating cycle on Base mainnet without violating money invariants.

The target is not scale.
The target is confidence.

We want one intentionally small, fully traceable, low-risk cycle that proves:

1. chain reads are correct
2. accounting ingestion is correct
3. reconciliation behaves correctly
4. at least one small real payout/accounting proof works
5. alerts remain clean

## Preconditions

This runbook must only be executed after:

1. `docs/BASE_MAINNET_DEPLOY_RUNBOOK.md` is complete
2. `docs/BASE_MAINNET_ENV_CUTOVER_RUNBOOK.md` is complete
3. Mainnet `DividendDistributor` ownership is verified on-chain
4. `prod_preflight --run-ops-smoke --fail-on-warning` passes under mainnet configuration
5. `/api/v1/indexer/status` is healthy on mainnet
6. `/api/v1/alerts` has no critical alerts

## Safety Rules

This is a real-money test. Keep it intentionally small.

Rules:

- use minimal amounts only
- use only internal operator-controlled addresses
- do not involve external agents yet
- record every tx hash immediately
- stop immediately if any invariant becomes unclear

Recommended operating posture:

- one operator executes
- one operator reviews
- no parallel unrelated changes during the smoke window

## Suggested Minimal Amounts

Exact values depend on operational comfort, but they should be deliberately tiny.

Example envelope:

- funding deposit: very small USDC amount
- invoice/payment: very small USDC amount
- expense/payout proof: very small USDC amount

The specific numbers should be low enough that loss is tolerable, but high enough to prove the full path works with real mainnet confirmations.

## Required Evidence Log

Before starting, prepare a simple operator log for:

- timestamp of each step
- actor/operator
- tx hash
- expected effect
- observed effect
- stop/go decision

This can be a local operator note or structured JSON, but it must exist.

## Smoke Sequence

### Step 1: Pre-Flight Snapshot

Record:

- current `/api/v1/health`
- current `/api/v1/stats`
- current `/api/v1/indexer/status`
- current `/api/v1/alerts`

This becomes the “before” baseline.

### Step 2: Minimal Internal Funding

Perform one tiny internal funding deposit into the intended project treasury.

Expected result:

- the transfer lands on-chain
- the system can observe or ingest it
- project capital accounting can reconcile back to strict-ready

Required checks:

- treasury balance changes as expected
- corresponding capital event exists
- project capital reconciliation returns:
  - `ready=true`
  - `delta_micro_usdc=0`

Stop if:

- observed balance and ledger diverge
- reconciliation blocks unexpectedly

### Step 3: Minimal Internal Invoice / Revenue Proof

Create one internal invoice and pay it with a tiny real USDC transfer to the project revenue address.

Expected result:

- invoice is created
- payment lands on-chain
- billing sync marks it as paid
- revenue-side timeline reflects the event

Required checks:

- invoice status changes to `paid`
- payment tx hash is recorded
- `project_updates` shows:
  - `crypto_invoice_paid`
  - `billing_settlement`

Stop if:

- invoice does not match the transfer
- billing sync produces inconsistent state

### Step 4: Revenue/Project Reconciliation

Run the corresponding reconciliation step(s) after the payment.

Expected result:

- on-chain and ledger values match for the tested path
- no unexpected `rpc_error`, `balance_mismatch`, or stale failure appears

Required checks:

- reconciliation reports are fresh
- if the tested amount is supposed to be fully represented in ledger:
  - `ready=true`
  - `delta_micro_usdc=0`

### Step 5: Minimal Expense / Payout Proof

Execute one tiny internal expense path or equivalent small payout proof.

This does not need to be a full public bounty flow.
It can be the smallest safe real-money expense path that proves:

- a spend event can be recorded
- the ledger remains coherent
- reconciliation gates still behave correctly after spend

Required checks:

- expense event exists with evidence
- project balance changes by the expected amount
- post-spend reconciliation is still coherent

Stop if:

- spend lands on-chain but ledger does not reflect it
- ledger reflects spend but chain state does not

### Step 6: Post-Flight Snapshot

Repeat the same checks as Step 1:

- `/api/v1/health`
- `/api/v1/stats`
- `/api/v1/indexer/status`
- `/api/v1/alerts`

Required success condition:

- no critical alerts
- no unexpected warning spike
- indexer remains healthy

## Required Success Criteria

The internal mainnet smoke is considered successful only if all of the following are true:

1. At least one tiny real funding movement is confirmed and reconciled.
2. At least one tiny real invoice/payment is confirmed and reflected in billing/revenue state.
3. At least one tiny real spend/expense proof is confirmed and reflected coherently.
4. All corresponding tx hashes are recorded.
5. Reconciliation remains strict-ready where expected.
6. Alerts remain clean enough to proceed.

## Failure Handling

If any step fails:

1. Stop the smoke loop immediately.
2. Do not continue to public launch.
3. Record:
   - last successful step
   - failing step
   - tx hash (if any)
   - observed mismatch
4. Prefer controlled roll-forward only after the mismatch is understood.
5. If needed, revert live environment configuration back to the known-good previous state using:
   - `docs/BASE_MAINNET_ENV_CUTOVER_RUNBOOK.md`

## What This Runbook Does Not Do

This runbook does not itself authorize:

- external-agent public launch
- raising limits
- removing operator oversight

It only proves that the first real-money mainnet cycle is operationally viable.

## Next Step

If this internal smoke run succeeds:

1. capture a final go/no-go snapshot
2. review all evidence and tx hashes
3. only then consider controlled external-agent enablement
