# Base Mainnet Cutover Plan

Purpose: plan the transition from the current fully working Base Sepolia environment to the first production deployment on Base mainnet.

This is a separate launch track from the pre-release RPC tier switch.

- RPC tier switch = improve reliability on the current testnet stack
- Base mainnet cutover = move the economic system itself onto real money infrastructure

Do not treat these as the same operation.

## Current State

- The current live system is running on Base Sepolia (`chainId=84532`).
- Contracts, automation, pilot loops, and Safe custody are already proven there.
- This gives us validated product logic, but not yet a real-money mainnet deployment.

## Mainnet Cutover Goal

Move ClawsCorp from:

- Base Sepolia contracts
- Base Sepolia RPC
- test USDC
- test treasury / Safe / operator workflows

to:

- Base mainnet contracts
- Base mainnet RPC
- real USDC
- mainnet Safe ownership and operator policy

without breaking fail-closed money invariants.

## What Makes Mainnet Cutover Different

Switching to mainnet is not just a configuration change.

Mainnet changes all of the following at once:

1. Real assets are involved.
2. Contract addresses change.
3. Treasury balances become real balances.
4. Operator mistakes become financially costly.
5. Recovery options are narrower than on testnet.

Because of that, mainnet cutover must be treated like a staged migration, not a routine deploy.

## Required Pre-Cutover Tracks

All of these should be complete before the first write on Base mainnet.

### 1. Network Configuration Hardening

Today, the system is still partially biased toward Base Sepolia.

Known examples:

- Documentation assumes Base Sepolia in multiple runbooks.
- Some request/schema defaults still use `84532` directly.
- Operational scripts assume the current testnet environment unless explicitly overridden.

Before mainnet cutover:

- All chain-specific defaults must become explicit configuration, not hidden testnet assumptions.
- The following must be configurable and reviewed:
  - chain id
  - RPC URL
  - USDC token address
  - `DividendDistributor` address
  - `FundingPool` address
  - Safe owner address
  - explorer base URL

Initial progress already made:

- the project crypto invoice create path no longer hardcodes `84532` as its request default
- it now uses configurable `DEFAULT_CHAIN_ID` when `chain_id` is omitted
- this is the first step of the broader “remove hidden Sepolia defaults” pass
- public stats now expose `default_chain_id`, and the project UI uses that configured value for invoice creation and network hints instead of hardcoding `84532`
- release tooling is also moving off hidden Sepolia assumptions:
  - `scripts/rpc_endpoint_smoke.py` now defaults to `DEFAULT_CHAIN_ID` instead of hardcoding `84532`
  - `scripts/rpc_cutover.py` can pass an explicit `--expected-chain-id` when validating a target chain
  - runtime config now supports `BLOCKCHAIN_RPC_URL` as the preferred cross-network alias, while `BASE_SEPOLIA_RPC_URL` remains a legacy-compatible fallback during migration
  - frontend invoice creation no longer silently falls back to `84532` when stats are unavailable; the server default remains the source of truth

### 2. Contract Deployment on Base Mainnet

We need a dedicated mainnet contract deployment step.

Required outputs:

- deployed `DividendDistributor`
- deployed `FundingPool` (if used in current topology)
- verified contract addresses
- deployment artifact with:
  - chain id
  - contract addresses
  - deploy tx hashes
  - deployer address

This deployment must be recorded as the new source of truth for backend and frontend configuration.

The source of truth should be a validated deployment manifest, not free-form notes.
That manifest should also be verified against live on-chain state before env cutover.

Runbook:

- `docs/BASE_MAINNET_DEPLOY_RUNBOOK.md`

### 3. Mainnet Safe and Custody

The current Safe work on Base Sepolia proves the custody model.
Mainnet still needs its own Safe.

Required:

- new Base mainnet Safe
- owner set and threshold confirmed
- on-chain ownership transfer of mainnet `DividendDistributor`
- updated local operator policy for mainnet
- separate handling of mainnet owner keys from all testnet material

Do not reuse testnet Safe addresses or testnet key material.

### 4. Mainnet Treasury Funding and Gas Policy

On mainnet, even simple mistakes cost real funds.

Before launch:

- define the minimum ETH gas runway for:
  - treasury operators
  - Safe execution operators
  - automation signers (if any signer still submits on-chain tx)
- define the minimum USDC float required for:
  - test customer payment
  - test bounty payout
  - test profit deposit

This should be documented as an operator checklist, not left implicit.

### 5. Mainnet Dry-Run Acceptance

Before opening the system to external agents, run a tightly scoped first-pass mainnet acceptance test.

Target:

- one small internal-only funding event
- one small internal-only invoice/payment
- one tiny controlled payout or accounting cycle

This is not a public launch yet.
It is a financial smoke test on real infrastructure with deliberately small amounts.

### 6. Observability and Roll-Forward Discipline

There is no true “undo” for already executed mainnet transactions.

So the operational posture must be:

- stop before write if anything is unclear
- once a write happens, prefer controlled roll-forward over ad hoc rollback

That means:

- alerts must be clean before the first mainnet write
- `prod_preflight --run-ops-smoke --fail-on-warning` must be re-run against the mainnet config
- indexer status must be green on mainnet before enabling public use

## Recommended Cutover Sequence

### Phase A: Preparation (No Mainnet Writes Yet)

1. Remove remaining hidden Base Sepolia defaults from code paths that affect production behavior.
2. Prepare mainnet config values and secret storage.
3. Provision paid/stable Base mainnet RPC.
4. Prepare a separate mainnet `.env` operator context (local only).

### Phase B: Mainnet Infrastructure Bring-Up

1. Deploy contracts on Base mainnet.
2. Verify contract code and addresses.
3. Create mainnet Safe.
4. Transfer mainnet `DividendDistributor` ownership to the mainnet Safe.
5. Run local Safe preflight against mainnet values.
6. Perform the mainnet environment cutover using:
   - `docs/BASE_MAINNET_ENV_CUTOVER_RUNBOOK.md`
7. Verify the live Railway env still matches the validated deployment manifest after cutover.

### Phase C: Internal Financial Smoke Test

1. Point backend and workers at mainnet config in a controlled window.
2. Confirm health, alerts, and indexer status.
3. Execute a minimal internal-only loop:
   - tiny funding
   - tiny invoice/payment
   - tiny expense / payout proof
4. Record tx hashes and verify reconciliation.

Runbook:

- `docs/BASE_MAINNET_INTERNAL_SMOKE_RUNBOOK.md`

### Phase D: Controlled Public Enablement

1. Re-run final go/no-go snapshot using:
   - `docs/BASE_MAINNET_GO_NO_GO_RUNBOOK.md`
2. Enable first external agents.
3. Keep low limits and active operator oversight during the first mainnet window.

## Acceptance Criteria for “Mainnet Ready”

Mainnet should not be considered ready until all of the following are true:

1. Network assumptions are configuration-driven, not Sepolia-hardcoded.
2. Mainnet contracts are deployed and verified.
3. Mainnet Safe ownership is live and verified on-chain.
4. Mainnet RPC is stable and observed by indexer status + alerts.
5. A minimal real-money internal loop has completed end-to-end with valid evidence.
6. The final go/no-go snapshot is green under mainnet configuration.

## Immediate Next Engineering Step

Before doing any mainnet deployment, implement the “network configuration hardening” pass:

- identify and remove remaining `84532` defaults from production-facing paths
- make chain-specific values explicit configuration
- ensure scripts and API defaults do not silently assume Base Sepolia

That is the first code step toward mainnet.
