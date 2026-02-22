# Oracle Signer Key Rotation Runbook

This runbook rotates the backend signer key used by tx-worker/oracle endpoints without breaking autonomy.

## Scope

Covers:
- `ORACLE_SIGNER_PRIVATE_KEY` rotation
- post-rotation validation (`tx-worker`, `run-month`, alerts)

Does not cover contract ownership migration to Safe (see `docs/SAFE_MIGRATION_PLAN.md`).

## Preconditions

- New signer key generated and stored in secret manager (never in git).
- New signer wallet has enough Base Sepolia ETH for gas.
- If required by contracts/policy, new signer is authorized for submissions.
- `ORACLE_HMAC_SECRET` remains unchanged unless explicitly rotating auth secret too.

## Rotation Steps (Railway)

1. Pause autonomous writers (temporary):
- stop or scale down `autonomy-loop`
- stop or scale down `tx-worker`

2. Set new secret in Railway for backend/worker services:
- `ORACLE_SIGNER_PRIVATE_KEY=<new_key>`

3. Redeploy services that use signer key:
- backend
- tx-worker
- autonomy-loop (if it performs write calls)

4. Resume workers:
- start `tx-worker`
- start `autonomy-loop`

## Validation Checklist

1. Health and alerts:
```bash
python3 scripts/prod_preflight.py --timeout-seconds 20
```

2. Write-path smoke (includes tx-worker and reconcile):
```bash
python3 scripts/prod_preflight.py \
  --run-ops-smoke \
  --ops-smoke-env-file /Users/alex/.oracle.env \
  --ops-smoke-month auto \
  --ops-smoke-tx-max-tasks 3
```

3. Optional tx proof (if pending task exists):
- confirm a new outbox task moves `pending -> processing -> succeeded`.

4. Ensure no new critical alerts:
- `tx_outbox_failed`
- `platform_profit_deposit_failed`
- auth/replay spikes

## Rollback

If rotation fails:
1. Pause writers again (`autonomy-loop`, `tx-worker`).
2. Restore previous known-good signer key secret.
3. Redeploy backend + worker services.
4. Re-run preflight + ops smoke.

## Audit Notes (what to record)

Record in incident/ops log:
- date/time (UTC)
- actor
- services restarted
- validation command outputs summary
- any tx hashes submitted after rotation
