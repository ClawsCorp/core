# Base Mainnet Environment Cutover Runbook

Purpose: switch the live application environment from the current Base Sepolia configuration to the new Base mainnet configuration after contracts are already deployed and ownership is already transferred to the mainnet Safe.

This runbook is the configuration cutover step.

It must only be used after:

- `docs/BASE_MAINNET_DEPLOY_RUNBOOK.md` is completed
- the deployment manifest exists
- mainnet Safe ownership is verified on-chain

## What This Step Changes

This step changes the live environment from testnet references to mainnet references.

That includes:

- RPC endpoint
- chain id defaults
- contract addresses
- token address
- Safe owner address
- any UI network hints derived from backend config

It does **not** mean “public launch is complete”.
After this cutover, we still need the internal real-money smoke loop before opening the system to external agents.

## Source of Truth

All values used in this cutover must come from the mainnet deployment manifest captured during:

- `docs/BASE_MAINNET_DEPLOY_RUNBOOK.md`

Do not type addresses from memory.
Do not reuse Sepolia addresses.

## Required Mainnet Values

At minimum, the operator must have:

- `BASE_MAINNET_RPC_URL`
- `DEFAULT_CHAIN_ID=8453`
- `USDC_ADDRESS` (Base mainnet USDC)
- `DIVIDEND_DISTRIBUTOR_CONTRACT_ADDRESS`
- `FUNDING_POOL_CONTRACT_ADDRESS` (if used in the active topology)
- `SAFE_OWNER_ADDRESS`
- `MARKETING_TREASURY_ADDRESS` (mainnet address if distinct)

Likely related project/application values:

- explorer base URL for Base mainnet
- any mainnet treasury/revenue addresses used in first internal smoke projects

## Services Affected

Railway:

- `core`
- `usdc-indexer`
- `tx-worker`
- `autonomy-loop`

Potential frontend runtime configuration:

- Vercel env if the frontend uses explicit environment variables for API or explorer hints

## Pre-Cutover Preconditions

All of the following should be true before touching live config:

1. Mainnet contracts are deployed.
2. Mainnet `DividendDistributor` owner is the mainnet Safe.
3. Mainnet RPC passes local smoke:

```bash
python3 scripts/rpc_endpoint_smoke.py \
  --rpc-url "$BASE_MAINNET_RPC_URL" \
  --expected-chain-id 8453 \
  --usdc-address "$USDC_ADDRESS" \
  --distributor-address "$DIVIDEND_DISTRIBUTOR_CONTRACT_ADDRESS"
```

4. Current production (still Sepolia) is healthy:
   - `/api/v1/health`
   - `/api/v1/indexer/status`
   - `/api/v1/alerts`

## Recommended Cutover Order

### Phase 1: Prepare Local Operator Context

Export the exact mainnet values locally first:

```bash
export BASE_MAINNET_RPC_URL='https://...'
export DEFAULT_CHAIN_ID='8453'
export USDC_ADDRESS='0x...'
export DIVIDEND_DISTRIBUTOR_CONTRACT_ADDRESS='0x...'
export FUNDING_POOL_CONTRACT_ADDRESS='0x...'
export SAFE_OWNER_ADDRESS='0x...'
export MARKETING_TREASURY_ADDRESS='0x...'
```

Run the local smoke again against these exact values before changing Railway.

### Phase 2: Update Railway Backend/Worker Config

Update `core`:

```bash
python3 scripts/railway_set_vars.py \
  --project-id cd76995a-d819-4b36-808b-422de3ff430e \
  --environment-name production \
  --service core \
  --set BASE_SEPOLIA_RPC_URL="$BASE_MAINNET_RPC_URL" \
  --set DEFAULT_CHAIN_ID="$DEFAULT_CHAIN_ID" \
  --set USDC_ADDRESS="$USDC_ADDRESS" \
  --set DIVIDEND_DISTRIBUTOR_CONTRACT_ADDRESS="$DIVIDEND_DISTRIBUTOR_CONTRACT_ADDRESS" \
  --set FUNDING_POOL_CONTRACT_ADDRESS="$FUNDING_POOL_CONTRACT_ADDRESS" \
  --set SAFE_OWNER_ADDRESS="$SAFE_OWNER_ADDRESS" \
  --set MARKETING_TREASURY_ADDRESS="$MARKETING_TREASURY_ADDRESS"
```

Update `usdc-indexer`:

```bash
python3 scripts/railway_set_vars.py \
  --project-id cd76995a-d819-4b36-808b-422de3ff430e \
  --environment-name production \
  --service usdc-indexer \
  --set BASE_SEPOLIA_RPC_URL="$BASE_MAINNET_RPC_URL" \
  --set USDC_ADDRESS="$USDC_ADDRESS"
```

Update `tx-worker`:

```bash
python3 scripts/railway_set_vars.py \
  --project-id cd76995a-d819-4b36-808b-422de3ff430e \
  --environment-name production \
  --service tx-worker \
  --set BASE_SEPOLIA_RPC_URL="$BASE_MAINNET_RPC_URL" \
  --set USDC_ADDRESS="$USDC_ADDRESS" \
  --set DIVIDEND_DISTRIBUTOR_CONTRACT_ADDRESS="$DIVIDEND_DISTRIBUTOR_CONTRACT_ADDRESS" \
  --set SAFE_OWNER_ADDRESS="$SAFE_OWNER_ADDRESS"
```

Update `autonomy-loop`:

```bash
python3 scripts/railway_set_vars.py \
  --project-id cd76995a-d819-4b36-808b-422de3ff430e \
  --environment-name production \
  --service autonomy-loop \
  --set BASE_SEPOLIA_RPC_URL="$BASE_MAINNET_RPC_URL" \
  --set USDC_ADDRESS="$USDC_ADDRESS" \
  --set DIVIDEND_DISTRIBUTOR_CONTRACT_ADDRESS="$DIVIDEND_DISTRIBUTOR_CONTRACT_ADDRESS"
```

Note:

- The variable names remain the current ones (`BASE_SEPOLIA_RPC_URL`, etc.) until a later naming cleanup pass.
- This runbook changes the values first, not the variable names.

### Phase 3: Wait for Healthy Redeploys

```bash
RAILWAY_WORKSPACE_TOKEN=... python3 scripts/railway_health_check.py \
  --project-id cd76995a-d819-4b36-808b-422de3ff430e \
  --environment-name production
```

Required:

- all four services healthy
- no crash loops

### Phase 4: Verify Live Mainnet Configuration

Check:

```bash
curl -sS https://core-production-b1a0.up.railway.app/api/v1/health
curl -sS https://core-production-b1a0.up.railway.app/api/v1/stats
curl -sS https://core-production-b1a0.up.railway.app/api/v1/indexer/status
curl -sS https://core-production-b1a0.up.railway.app/api/v1/alerts
```

Key expectations:

- `default_chain_id = 8453`
- indexer chain data is live and not stale
- no critical alerts

### Phase 5: Run Formal Post-Cutover Validation

```bash
python3 scripts/prod_preflight.py \
  --run-ops-smoke \
  --ops-smoke-env-file /Users/alex/.oracle.env \
  --ops-smoke-month auto \
  --ops-smoke-tx-max-tasks 5 \
  --fail-on-warning
```

At this stage, the result should be interpreted as:

- “mainnet-configured environment is operational”

not yet:

- “public launch complete”

### Phase 6: Stop Before Public Launch

After successful environment cutover:

1. Do not immediately enable external agents.
2. First run the minimal internal real-money smoke loop on mainnet.
3. Only after that take the final public go/no-go decision.

## Rollback

If the environment becomes unstable after the cutover:

1. Reapply the last known-good Sepolia values to the same services.
2. Wait for healthy redeploys.
3. Re-run:
   - `/api/v1/health`
   - `/api/v1/indexer/status`
   - `/api/v1/alerts`
   - `prod_preflight --run-ops-smoke --fail-on-warning`

Rollback triggers include:

- stale or broken indexer
- RPC/config errors on reconciliation
- contract-address mismatch
- unexpected alert spikes
- incorrect owner/custody state

## Important Constraint

This runbook intentionally uses existing variable names even when they still contain “Sepolia” wording.

Reason:

- renaming environment variables and changing their values at the same time increases migration risk

Recommended policy:

1. First switch the values safely.
2. Only later perform naming cleanup in a separate refactor.

## Next Step

After this configuration cutover succeeds, the next required operational step is:

- a minimal internal real-money smoke loop on Base mainnet

That should be documented and executed before any public external-agent launch.
