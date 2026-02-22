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

## Required env

- `ORACLE_BASE_URL`
- `ORACLE_HMAC_SECRET`

You can export them directly, or pass `--env-file`.

## Exit code

- `0`: smoke run finished and no `critical` alerts remain.
- `1`: at least one `critical` alert exists after the run.
- `2`: invalid arguments or missing required env.

## Notes

- The script is idempotent-friendly (runner endpoints are designed for repeat calls).
- It does not call `marketing-deposit` automatically.
- If you need marketing settlement too, run it explicitly:

```bash
cd backend
python3 -m src.oracle_runner marketing-deposit --json
```
