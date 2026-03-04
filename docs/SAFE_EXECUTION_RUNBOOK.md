# Safe Execution Runbook

Operational runbook for the local-only Safe execution path used in testnet/pilot mode.

Purpose:

- keep `DividendDistributor` custody on Safe
- keep hosted services free of Safe owner private keys
- allow a local operator machine to run `tx-worker` with `SAFE_OWNER_KEYS_FILE`

## What This Runbook Covers

Use this only for owner-only distribution tasks:

- `create_distribution`
- `execute_distribution`

Do not store Safe owner private keys in Railway, Vercel, GitHub secrets, or tracked files.

Hosted production behavior remains:

- backend may enqueue tx outbox tasks
- hosted `tx-worker` may process non-owner tasks
- owner-only distribution tasks must stay blocked unless a local Safe executor is used

## Local Operator Machine

Current operating policy (pilot / pre-production):

- One designated operator machine is allowed to run the local Safe executor.
- The designated operator is the deployment custodian for the current environment.
- Hosted services may enqueue owner-only tasks, but they must not hold Safe owner keys.
- The local operator machine is the only place where `SAFE_OWNER_KEYS_FILE` may exist in plaintext form.
- If the designated operator machine changes, re-run preflight before the next owner-only execution cycle.

Required local-only inputs:

- `BLOCKCHAIN_RPC_URL` (preferred) or `BASE_SEPOLIA_RPC_URL` (legacy fallback)
- `DIVIDEND_DISTRIBUTOR_CONTRACT_ADDRESS`
- `SAFE_OWNER_ADDRESS`
- `SAFE_OWNER_KEYS_FILE`
- `ORACLE_BASE_URL`
- `ORACLE_HMAC_SECRET`

Recommended storage:

- keep `SAFE_OWNER_KEYS_FILE` outside the repo
- file permissions should be `0600`
- keep it on a single operator machine or encrypted local secret store
- keep `ORACLE_HMAC_SECRET` in a local env file or local secret manager, not in shell history

Operational responsibility split:

- Railway / hosted backend:
  - computes settlement state
  - enqueues owner-only tasks
  - records tx state
- Local Safe executor:
  - runs preflight
  - executes owner-only Safe transactions
  - stops immediately on preflight failure or unexpected Safe mismatch

## Preflight (Must Pass Before Running Local Safe Execution)

Run:

```bash
python3 scripts/safe_execution_preflight.py --envfile /Users/alex/.oracle.env
```

Expected result:

- `success=true`
- `blocked_reasons=[]`
- `owner_check.matches_expected_owner=true`
- `keys_file.secure_permissions=true`
- `keys_file.private_keys_count >= keys_file.threshold`

Typical blocked reasons:

- `missing_safe_owner_keys_file`
- `missing`
- `permissions_too_open`
- `invalid_json`
- `owners_missing`
- `invalid_threshold`
- `insufficient_keys_for_threshold`
- `missing_rpc_url`
- `missing_contract_address`
- `missing_safe_owner_address`
- `owner_mismatch`
- `owner_check_failed:...`

## Running The Local Safe Executor

After preflight:

```bash
cd backend
PYTHONPATH=src python -m oracle_runner tx-worker --loop --max-tasks 10
```

Behavior:

- non-owner tasks execute normally
- owner-only distribution tasks use Safe `execTransaction`
- resulting on-chain `tx_hash` is written back into backend

## If A Task Stays Blocked

If `tx_outbox` shows `safe_execution_required`:

1. Confirm `SAFE_OWNER_ADDRESS` is set locally.
2. Confirm `SAFE_OWNER_KEYS_FILE` is set locally.
3. Run `scripts/safe_execution_preflight.py`.
4. Re-run local `tx-worker`.

If preflight passes and tasks still fail:

1. Inspect `tx_outbox.last_error_hint`
2. Verify Safe owner still matches on-chain
3. Verify RPC health
4. Verify owner key file still contains enough keys for threshold

## Security Rules

- Never commit `SAFE_OWNER_KEYS_FILE`
- Never copy Safe owner private keys into hosted secrets
- Never print private keys in logs
- Rotate the local key file only by replacing the local file, then re-run preflight

## Production Position

This is an acceptable pilot/testnet operating model.

For full production autonomy, the next step is to remove private-key execution from local machines and move to a stricter Safe proposal/approval flow where the backend generates payloads and custody remains outside the app runtime.
