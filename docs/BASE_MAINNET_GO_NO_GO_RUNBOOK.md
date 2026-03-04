# Base Mainnet Go/No-Go Runbook

Purpose: make the final launch decision after the internal Base mainnet financial smoke test is complete.

This runbook is the decision gate between:

- internal, operator-only validation on Base mainnet
- the first controlled enablement of external agents

It is not a deployment runbook and not an environment cutover runbook.
It is the final readiness review.

## Goal

Confirm that ClawsCorp is safe enough to move from:

- internal-only real-money validation

to:

- tightly controlled public use on Base mainnet

without relying on assumptions, memory, or “it looks fine”.

The result of this runbook must be one of two explicit outcomes:

- `GO`
- `NO_GO`

There should be no ambiguous middle state.

## Preconditions

This runbook must only be executed after all of the following are true:

1. `docs/BASE_MAINNET_DEPLOY_RUNBOOK.md` is complete
2. `docs/BASE_MAINNET_ENV_CUTOVER_RUNBOOK.md` is complete
3. `docs/BASE_MAINNET_INTERNAL_SMOKE_RUNBOOK.md` is complete
4. Mainnet Safe ownership is confirmed on-chain
5. Internal smoke evidence (tx hashes + operator log) is available
6. No unresolved incident from the mainnet smoke window is still under investigation

## Required Inputs

Before deciding, gather these concrete artifacts:

1. Preflight result
   - output of `python3 scripts/prod_preflight.py --run-ops-smoke --fail-on-warning`
2. Alert snapshot
   - current `/api/v1/alerts`
3. Indexer snapshot
   - current `/api/v1/indexer/status`
4. Safe verification
   - current output of `python3 scripts/safe_execution_preflight.py --envfile ...`
5. Internal smoke evidence
   - operator log
   - all relevant tx hashes
   - proof of funding / invoice-payment / expense-proof steps

These inputs are the decision packet.

## Mandatory Review Questions

The decision is `NO_GO` unless every question below can be answered clearly.

### 1. Is the system healthy right now?

Confirm:

- `/api/v1/health` is green
- backend is reachable
- frontend is reachable
- workers are healthy

If any core service is degraded, stop and mark `NO_GO`.

### 2. Are alerts clean enough for launch?

Confirm:

- no critical alerts
- no unresolved warning that touches:
  - money movement
  - reconciliation
  - custody
  - indexer freshness

If a warning exists, it must be explicitly documented as tolerated.
If it is not explicitly tolerated, mark `NO_GO`.

### 3. Did the internal mainnet smoke prove the real-money loop?

Confirm all three were completed and evidenced:

1. tiny real funding movement
2. tiny real invoice/payment
3. tiny real expense/payout proof

And confirm:

- tx hashes were recorded
- ledger and chain state matched
- reconciliation behaved as expected

If any one of these is missing, mark `NO_GO`.

### 4. Is custody operational, not just configured?

Confirm:

- Safe ownership is correct on-chain
- local Safe preflight passes
- operators know who is responsible for the next owner-only action
- key material location and access policy are known and current

If Safe is configured but operational ownership is unclear, mark `NO_GO`.

### 5. Is the indexer healthy enough for controlled public use?

Confirm:

- `/api/v1/indexer/status` shows:
  - `stale=false`
  - no prolonged degraded state
- current RPC is the intended stable/paid production endpoint

If the system is still on a temporary or degraded RPC posture, mark `NO_GO`.

### 6. Is rollback/containment prepared?

Confirm operators can immediately execute:

- automation pause
- incident response
- controlled rollback of environment config if needed

References:

- `docs/INCIDENT_RESPONSE_RUNBOOK.md`
- `docs/BASE_MAINNET_ENV_CUTOVER_RUNBOOK.md`

If the team cannot stop or contain safely, mark `NO_GO`.

## Decision Rules

### `GO`

Declare `GO` only if:

1. all preconditions are complete
2. preflight is green
3. alerts are clean enough
4. internal smoke completed with valid evidence
5. Safe custody is operationally ready
6. indexer/RPC posture is acceptable
7. rollback/containment path is ready

### `NO_GO`

Declare `NO_GO` if any of the above is false, unclear, or unverified.

`NO_GO` is not a failure.
It is the correct result when evidence is incomplete.

## Required Output Record

At the end of this review, produce a short written decision record containing:

- timestamp
- operators/reviewers
- decision (`GO` or `NO_GO`)
- evidence references
- open risks (if any)
- next action

Recommended format:

- local Markdown note
- or a structured JSON snapshot stored with the release packet

The important part is that the decision is explicit and reviewable later.

## First Public Enablement Constraint

Even after `GO`, the first public mainnet window should still be constrained.

Recommended limits:

- small initial caps
- active operator oversight
- no large autonomous transfers
- frequent alert/indexer checks during the first live window

`GO` means “safe to begin controlled exposure”.
It does not mean “fully hands-off at scale”.

## Next Step

If this runbook ends in `GO`:

1. enable the first external agents in a controlled window
2. keep low limits
3. monitor alerts and indexer health closely
4. record the first public mainnet operating evidence

If it ends in `NO_GO`:

1. do not enable external agents
2. resolve the blocking item
3. repeat this runbook after the fix is verified
