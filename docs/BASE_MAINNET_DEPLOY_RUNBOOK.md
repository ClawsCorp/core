# Base Mainnet Contract Deployment Runbook

Purpose: perform the first controlled contract deployment on Base mainnet and capture the deployment artifacts needed for the later full mainnet cutover.

This runbook is for contract bring-up only.

It does not itself complete the full production migration.
It prepares the on-chain base required for:

- mainnet Safe ownership
- mainnet backend configuration
- mainnet internal financial smoke testing

## Scope

Contracts in the current MVP topology:

- `DividendDistributor`
- `FundingPool`

Related but separate:

- mainnet Safe deployment
- ownership transfer of mainnet `DividendDistributor`

## Current Preconditions

Before running this:

1. Network configuration hardening is already underway.
2. `contracts/hardhat.config.js` now supports:
   - `baseSepolia` via `BASE_SEPOLIA_RPC_URL`
   - `base` via `BASE_MAINNET_RPC_URL`
3. You have a paid/stable Base mainnet RPC endpoint.
4. You have a dedicated deployer key for mainnet.
5. You have the correct Base mainnet USDC address and the intended treasury/founder addresses.

## Required Environment (Local Only)

Minimum:

- `BASE_MAINNET_RPC_URL`
- `DEPLOYER_PRIVATE_KEY` or `ORACLE_SIGNER_PRIVATE_KEY`
- `USDC_ADDRESS`

For `DividendDistributor` deployment:

- `TREASURY_WALLET_ADDRESS`
- `FOUNDER_WALLET_ADDRESS`

Example shell setup:

```bash
export BASE_MAINNET_RPC_URL='https://...'
export DEPLOYER_PRIVATE_KEY='0x...'
export USDC_ADDRESS='0x...'
export TREASURY_WALLET_ADDRESS='0x...'
export FOUNDER_WALLET_ADDRESS='0x...'
```

Do not store these values in tracked files.

## Pre-Deployment Validation

1. Confirm the target RPC is really Base mainnet:

```bash
python3 scripts/rpc_endpoint_smoke.py \
  --rpc-url "$BASE_MAINNET_RPC_URL" \
  --expected-chain-id 8453 \
  --usdc-address "$USDC_ADDRESS"
```

2. Confirm Hardhat sees the `base` network:

```bash
cd contracts
node --check hardhat.config.js
BASE_MAINNET_RPC_URL="$BASE_MAINNET_RPC_URL" npx hardhat help --network base
```

3. Confirm the deployer wallet has enough ETH for gas.

## Deployment Order

Recommended order:

1. `FundingPool`
2. `DividendDistributor`
3. mainnet Safe
4. ownership transfer to Safe

This keeps contract addresses explicit before custody handoff.

## 1. Deploy FundingPool

```bash
cd contracts
export BASE_MAINNET_RPC_URL='https://...'
export DEPLOYER_PRIVATE_KEY='0x...'
export USDC_ADDRESS='0x...'
npx hardhat run scripts/deploy-funding-pool.js --network base
```

Expected output:

- `FundingPool deployed to: 0x...`

Record:

- deployed address
- deploy tx hash (from RPC/explorer)
- deployer address

## 2. Deploy DividendDistributor

```bash
cd contracts
export BASE_MAINNET_RPC_URL='https://...'
export DEPLOYER_PRIVATE_KEY='0x...'
export USDC_ADDRESS='0x...'
export TREASURY_WALLET_ADDRESS='0x...'
export FOUNDER_WALLET_ADDRESS='0x...'
npx hardhat run scripts/deploy-dividend-distributor.js --network base
```

Expected output:

- `DividendDistributor deployed to: 0x...`

Record:

- deployed address
- deploy tx hash
- deployer address
- treasury wallet used
- founder wallet used

## 3. Deploy Mainnet Safe

Use the same Safe deployment script, but on Base mainnet and with new mainnet-only owners.

```bash
cd contracts
export BASE_MAINNET_RPC_URL='https://...'
export DEPLOYER_PRIVATE_KEY='0x...'
export SAFE_OWNER_ADDRESSES='0xowner1,0xowner2,0xowner3'
export SAFE_THRESHOLD='2'
export SAFE_SINGLETON_ADDRESS='0x...'
export SAFE_PROXY_FACTORY_ADDRESS='0x...'
export SAFE_FALLBACK_HANDLER_ADDRESS='0x...'
npx hardhat run scripts/deploy-safe-2of3.js --network base
```

Record:

- `safe_address`
- owners
- threshold
- deployment tx hash

## 4. Transfer DividendDistributor Ownership to the Mainnet Safe

```bash
cd contracts
export BASE_MAINNET_RPC_URL='https://...'
export DEPLOYER_PRIVATE_KEY='0x...'
export DIVIDEND_DISTRIBUTOR_CONTRACT_ADDRESS='0x...'
export SAFE_OWNER_ADDRESS='0x...'
npx hardhat run scripts/transfer-dividend-distributor-ownership.js --network base
```

Then verify:

```bash
cd contracts
export BASE_MAINNET_RPC_URL='https://...'
export DIVIDEND_DISTRIBUTOR_CONTRACT_ADDRESS='0x...'
export SAFE_OWNER_ADDRESS='0x...'
npx hardhat run scripts/check-dividend-distributor-owner.js --network base
```

Required success condition:

- `matches_expected_owner=true`

## Deployment Artifact (Required Output)

After deployment, capture one deployment manifest containing:

- chain id: `8453`
- deployment timestamp
- deployer address
- `USDC_ADDRESS`
- `FundingPool` address
- `DividendDistributor` address
- mainnet Safe address
- tx hashes for:
  - `FundingPool` deploy
  - `DividendDistributor` deploy
  - Safe deploy
  - ownership transfer

Canonical example:

- `docs/BASE_MAINNET_DEPLOYMENT_MANIFEST.example.json`

Required validation before using this manifest as the cutover source of truth:

```bash
python3 scripts/validate_mainnet_deploy_manifest.py path/to/base-mainnet-deploy.json
```

This manifest becomes the configuration source of truth for:

- Railway backend
- Railway workers
- frontend explorer links and network labels
- later mainnet go/no-go validation

## Immediate Post-Deployment Checks

After all four steps:

1. Verify owner state on-chain.
2. Verify contracts respond at the expected addresses.
3. Validate the deployment manifest with `scripts/validate_mainnet_deploy_manifest.py`.
4. Store the validated deployment manifest locally and in secure operator records.
5. Do not switch the live backend to mainnet yet unless the next mainnet cutover phase is planned and staffed.

## What This Runbook Does Not Do

This runbook does not yet:

- reconfigure Railway to mainnet
- move the public portal to mainnet mode
- run the internal real-money smoke loop
- open the system to external agents

Those happen in later phases of:

- `docs/BASE_MAINNET_CUTOVER_PLAN.md`

## Next Step After Deployment

Once contracts are deployed and ownership is on the mainnet Safe:

1. prepare the mainnet backend/worker env set
2. run a minimal internal-only mainnet financial smoke loop
3. only then consider external-agent enablement
