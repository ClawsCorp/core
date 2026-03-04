# RPC Provider Switch Runbook

Purpose: switch Base Sepolia RPC access from the current limited tier to the paid/stable provider tier immediately before external production launch, with a clear rollback path.

Current state:

- Current provider: Alchemy (`base-sepolia.g.alchemy.com`)
- Current operational risk: free-tier or limited RPC behavior can slow the indexer and make contributor/cap-table freshness lag
- Current mitigation already in place:
  - adaptive indexer span reduction
  - `GET /api/v1/indexer/status`
  - `usdc_indexer_degraded` alert

This runbook is intentionally a pre-release operation. Do not rotate the RPC endpoint casually during active debugging unless the old endpoint is clearly unstable.

## Scope

Services that must use the same Base Sepolia RPC endpoint:

- `core`
- `usdc-indexer`
- `tx-worker`
- `autonomy-loop`

Required environment variable:

- `BASE_SEPOLIA_RPC_URL`

## Success Criteria

After the switch:

- all four services are redeployed successfully
- `GET /api/v1/indexer/status` returns `200`
- `degraded=false` and `stale=false`
- `prod_preflight --run-ops-smoke --fail-on-warning` passes
- `/api/v1/alerts` has no critical or warning items

## Pre-Change Checklist

1. Provision the new RPC endpoint/key with the target provider or Alchemy paid tier.
2. Confirm the new endpoint responds for Base Sepolia.
3. Keep the previous working RPC URL available for rollback.
4. Confirm current production state is stable before the change:
   - `GET /api/v1/health`
   - `GET /api/v1/indexer/status`
   - `GET /api/v1/alerts`

## Change Procedure

1. Export the new endpoint only in the local operator shell:

```bash
export NEW_BASE_SEPOLIA_RPC_URL='https://...'
```

2. Update Railway service variables.

`core`:

```bash
python3 scripts/railway_set_vars.py \
  --project-id cd76995a-d819-4b36-808b-422de3ff430e \
  --environment-name production \
  --service core \
  --set BASE_SEPOLIA_RPC_URL="$NEW_BASE_SEPOLIA_RPC_URL"
```

`usdc-indexer`:

```bash
python3 scripts/railway_set_vars.py \
  --project-id cd76995a-d819-4b36-808b-422de3ff430e \
  --environment-name production \
  --service usdc-indexer \
  --set BASE_SEPOLIA_RPC_URL="$NEW_BASE_SEPOLIA_RPC_URL"
```

`tx-worker`:

```bash
python3 scripts/railway_set_vars.py \
  --project-id cd76995a-d819-4b36-808b-422de3ff430e \
  --environment-name production \
  --service tx-worker \
  --set BASE_SEPOLIA_RPC_URL="$NEW_BASE_SEPOLIA_RPC_URL"
```

`autonomy-loop`:

```bash
python3 scripts/railway_set_vars.py \
  --project-id cd76995a-d819-4b36-808b-422de3ff430e \
  --environment-name production \
  --service autonomy-loop \
  --set BASE_SEPOLIA_RPC_URL="$NEW_BASE_SEPOLIA_RPC_URL"
```

3. Wait for all affected services to reach healthy deploy state.

```bash
RAILWAY_WORKSPACE_TOKEN=... python3 scripts/railway_health_check.py \
  --project-id cd76995a-d819-4b36-808b-422de3ff430e \
  --environment-name production
```

4. Verify live chain-read health.

```bash
curl -sS https://core-production-b1a0.up.railway.app/api/v1/indexer/status
curl -sS https://core-production-b1a0.up.railway.app/api/v1/health
curl -sS https://core-production-b1a0.up.railway.app/api/v1/alerts
```

5. Run the formal post-change preflight.

```bash
python3 scripts/prod_preflight.py \
  --run-ops-smoke \
  --ops-smoke-env-file /Users/alex/.oracle.env \
  --ops-smoke-month auto \
  --ops-smoke-tx-max-tasks 5 \
  --fail-on-warning
```

6. Record the post-change snapshot:
   - timestamp
   - active provider
   - `/api/v1/indexer/status`
   - `prod_preflight` result
   - `/api/v1/alerts` result

## Rollback

If any of the following occur, roll back immediately:

- affected services fail to deploy cleanly
- `/api/v1/indexer/status` is unavailable after the switch
- `stale=true` or sustained `degraded=true`
- `prod_preflight` fails
- new RPC returns unstable or incorrect chain responses

Rollback procedure:

1. Export the previous known-good RPC URL:

```bash
export OLD_BASE_SEPOLIA_RPC_URL='https://...'
```

2. Repeat the same `scripts/railway_set_vars.py` updates for:
   - `core`
   - `usdc-indexer`
   - `tx-worker`
   - `autonomy-loop`

3. Wait for redeploy success.
4. Re-run:
   - `GET /api/v1/indexer/status`
   - `GET /api/v1/alerts`
   - `prod_preflight --run-ops-smoke --fail-on-warning`

## Notes

- Do not store the new RPC URL in tracked files.
- Keep provider keys only in Railway env and local operator env.
- This runbook is the final infrastructure cutover step before first external-agent production launch, not part of daily operations.
