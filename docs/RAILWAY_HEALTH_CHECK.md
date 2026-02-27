# Railway Service Health Check

Use `scripts/railway_health_check.py` to validate that the main production services are visible in Railway and have a healthy latest deployment state.

## Required env

- `RAILWAY_WORKSPACE_TOKEN`

## Default services checked

- `core`
- `usdc-indexer`
- `tx-worker`
- `autonomy-loop`

## Command

```bash
RAILWAY_WORKSPACE_TOKEN=... python3 scripts/railway_health_check.py \
  --project-id cd76995a-d819-4b36-808b-422de3ff430e \
  --environment-name production
```

## Output

JSON:
- `success`
- `environment_found`
- `services[]` with:
  - `name`
  - `found`
  - `deployment_status`
  - `deployment_id`
  - `deployment_created_at`
  - `health`

## Health interpretation

- `ok`: latest deployment status looks healthy (`SUCCESS`, `DEPLOYED`, `ACTIVE`, etc.)
- `warning`: latest deployment is still in progress
- `critical`: service missing or latest deployment failed
- `unknown`: status was returned but not recognized

## Notes

- This is read-only.
- The script never prints the token.
- If Railway GraphQL schema changes, update the query in `scripts/railway_health_check.py`.
