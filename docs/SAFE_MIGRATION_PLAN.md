# Safe / Multisig Ownership Migration (Plan)

Goal: remove single-owner custody from on-chain contracts and make ownership controlled by a Safe (multisig).

Scope (MVP):

- Transfer `DividendDistributor` ownership to a Safe on Base Sepolia.
- Keep backend/oracle runner as proposer/relayer only where needed; ideally backend becomes read-only for money-moving.
- Define an emergency policy (pause/stop) that is Safe-controlled.

Current production reality:

- `DividendDistributor` is still controlled by a single EOA path (`ORACLE_SIGNER_PRIVATE_KEY`).
- This is acceptable for pilot-stage guarded operation, but it is still a launch blocker for full production autonomy.
- The immediate goal is not just "have a plan", but make owner state observable and migration reproducible.

## Prereqs

- A Safe deployed on Base Sepolia (chainId `84532`).
- Confirm current owner EOA/key (current `ORACLE_SIGNER_PRIVATE_KEY` holder or equivalent).
- Confirm contract addresses:
  - `DIVIDEND_DISTRIBUTOR_CONTRACT_ADDRESS`
  - `USDC_ADDRESS`

## Migration Steps

0) Read-only preflight (before changing anything)

- Verify the current owner on-chain:

```bash
cd contracts
export BASE_SEPOLIA_RPC_URL=...
export DIVIDEND_DISTRIBUTOR_CONTRACT_ADDRESS=0x...
export SAFE_OWNER_ADDRESS=0x... # optional but recommended
npx hardhat run scripts/check-dividend-distributor-owner.js --network baseSepolia
```

- Expected output:
  - `owner=0x...`
  - `matches_expected_owner=true` only after migration is complete.
- If `matches_expected_owner=false`, production still depends on the old owner EOA.

1) Deploy / choose Safe

- Create Safe on Base Sepolia.
- Record Safe address as `SAFE_OWNER_ADDRESS`.
- Repo automation:

```bash
cd contracts
export BASE_SEPOLIA_RPC_URL=...
export ORACLE_SIGNER_PRIVATE_KEY=...
export SAFE_OWNER_ADDRESSES=0xowner1,0xowner2,0xowner3
export SAFE_THRESHOLD=2
export SAFE_SINGLETON_ADDRESS=0x41675C099F32341bf84BFc5382aF534df5C7461a
export SAFE_PROXY_FACTORY_ADDRESS=0x4e1DCf7AD4e460CfD30791CCC4F9c8a4f820ec67
export SAFE_FALLBACK_HANDLER_ADDRESS=0xfd0732Dc9E303f09fCEf3a7388Ad10A83459Ec99
npx hardhat run scripts/deploy-safe-2of3.js --network baseSepolia
```

- Output includes:
  - `safe_address=0x...`
  - `tx_hash=0x...`
  - owners + threshold used for deployment

2) Transfer ownership to Safe

- From current owner, call `transferOwnership(SAFE_OWNER_ADDRESS)` on `DividendDistributor`.
- Verify:
  - `owner()` returns `SAFE_OWNER_ADDRESS`.

Script (Hardhat):

```bash
cd contracts
export BASE_SEPOLIA_RPC_URL=...
export ORACLE_SIGNER_PRIVATE_KEY=...
export DIVIDEND_DISTRIBUTOR_CONTRACT_ADDRESS=0x...
export SAFE_OWNER_ADDRESS=0x...
npx hardhat run scripts/transfer-dividend-distributor-ownership.js --network baseSepolia
```

3) Update backend configuration

- Remove any implicit assumption that backend key is the on-chain owner.
- For any endpoints that currently send tx:
  - Change them to enqueue an outbox task (future) OR return "blocked: requires Safe execution".
- Local testnet automation mode is allowed:
  - set `SAFE_OWNER_ADDRESS`
  - set `SAFE_OWNER_KEYS_FILE` to a local JSON file containing the Safe owner private keys
  - run `tx-worker` locally so it can sign `execTransaction` with the required threshold and record the resulting tx hash
- This mode is for testnet/pilot automation only; owner key files must remain local-only and must not be stored in hosted secrets.

4) Emergency policy

- Document which actions are allowed without Safe vs require Safe.
  - Example MVP policy:
    - On-chain create/execute distribution: Safe-only.
    - Reconciliation / reads / payload generation: autonomous.
    - Emergency pause (if exists): Safe-only.

## Notes

- This doc is intentionally a plan: exact contract method names depend on the deployed ABI.
- Once tx-outbox worker exists, Safe can be integrated as:
  - direct Safe tx submission (propose), or
  - backend becomes pure observer + payload generator, Safe executes.
- The repo now includes two contract scripts for this flow:
  - `contracts/scripts/deploy-safe-2of3.js` (deploy a 2-of-3 Safe proxy with explicit owners)
  - `contracts/scripts/check-dividend-distributor-owner.js` (read-only verification)
  - `contracts/scripts/transfer-dividend-distributor-ownership.js` (state-changing transfer)
