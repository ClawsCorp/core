# Safe / Multisig Ownership Migration (Plan)

Goal: remove single-owner custody from on-chain contracts and make ownership controlled by a Safe (multisig).

Scope (MVP):

- Transfer `DividendDistributor` ownership to a Safe on Base Sepolia.
- Keep backend/oracle runner as proposer/relayer only where needed; ideally backend becomes read-only for money-moving.
- Define an emergency policy (pause/stop) that is Safe-controlled.

## Prereqs

- A Safe deployed on Base Sepolia (chainId `84532`).
- Confirm current owner EOA/key (current `ORACLE_SIGNER_PRIVATE_KEY` holder or equivalent).
- Confirm contract addresses:
  - `DIVIDEND_DISTRIBUTOR_CONTRACT_ADDRESS`
  - `USDC_ADDRESS`

## Migration Steps

1) Deploy / choose Safe

- Create Safe on Base Sepolia.
- Record Safe address as `SAFE_OWNER_ADDRESS`.

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
