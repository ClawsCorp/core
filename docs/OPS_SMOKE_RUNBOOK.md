# Ops Smoke Runbook

One-command smoke check for the autonomous runtime path:
- indexer ingestion (`billing-sync`, `project-capital-events/sync`)
- tx worker execution (`tx-worker`)
- platform reconciliation (`reconcile`)
- final alert gate (`/api/v1/alerts`)

## Command

```bash
scripts/ops_smoke.sh --env-file /Users/alex/.oracle.env --month auto --tx-max-tasks 5
```

Default behavior is fail-closed:
- if `reconcile` returns `ready=false`, smoke exits non-zero.
- if any runner step fails, smoke exits non-zero.

## Required env

- `ORACLE_BASE_URL`
- `ORACLE_HMAC_SECRET`

You can export them directly, or pass `--env-file`.

## Exit code

- `0`: smoke run finished and no `critical` alerts remain.
- `1`: a runner step failed or at least one `critical` alert exists after the run.
- `2`: invalid arguments or missing required env.

## Notes

- The script is idempotent-friendly (runner endpoints are designed for repeat calls).
- Runner step failures are fail-closed: the script exits immediately and does not mask errors.
- Reconcile must be strict-ready by default. For a temporary maintenance window, allow specific reasons:

```bash
scripts/ops_smoke.sh \
  --env-file /Users/alex/.oracle.env \
  --allow-reconcile-blocked-reason balance_mismatch
```

or via env:

```bash
export OPS_SMOKE_ALLOW_RECON_BLOCKED=balance_mismatch
```
- It does not call `marketing-deposit` automatically.
- If you need marketing settlement too, run it explicitly:

```bash
cd backend
python3 -m src.oracle_runner marketing-deposit --json
```

## GitHub Actions

Use workflow **`ops-smoke`** (`.github/workflows/ops-smoke.yml`) for one-click smoke runs in GitHub:
- inputs: `oracle_base_url`, `month`, `tx_max_tasks`
- required repository secret: `ORACLE_HMAC_SECRET`

## Combined with prod preflight

`scripts/prod_preflight.py` can run the same smoke in one report:

```bash
python3 scripts/prod_preflight.py \
  --run-ops-smoke \
  --ops-smoke-env-file /Users/alex/.oracle.env \
  --ops-smoke-month auto \
  --ops-smoke-tx-max-tasks 5
```
