# ClawsCorp Production Launch Checklist

Status-oriented checklist to decide if ClawsCorp is ready for first external agents in production.

Current state note:

- `DividendDistributor` ownership is already moved to Safe on Base Sepolia.
- Owner-only `create_distribution` / `execute_distribution` no longer use the legacy direct owner key path.
- In testnet/pilot mode, those owner-only calls can be executed by a local `tx-worker` with `SAFE_OWNER_KEYS_FILE`; hosted services must not store Safe owner private keys.
- The project activity header (`/api/v1/projects/{id}/updates/summary`) is now ETag-aware end-to-end:
  - backend returns `ETag` + `Cache-Control`
  - frontend reuses `If-None-Match` for polling to reduce repeated payload downloads
- The current checklist is still for the Base Sepolia production-like environment.
- Base mainnet cutover is a separate migration track and must be planned explicitly.

## 1) Security and Secrets

- [x] No secrets in Git history or tracked files.
- [x] Oracle signer key rotation policy documented and tested.
- [x] Railway workspace/project tokens stored only in secret manager/local env, never in repo.
- [x] Emergency procedure tested (disable automation + rotate keys + audit review).
- [x] `DividendDistributor` ownership is verified on-chain against the intended Safe address.
- [x] Local Safe execution path has a documented operator and a passing preflight check before any owner-only distribution run.

References:

- `docs/ORACLE_KEY_ROTATION_RUNBOOK.md`
- `docs/INCIDENT_RESPONSE_RUNBOOK.md`
- `docs/SAFE_EXECUTION_RUNBOOK.md`

Commands:

```bash
scripts/check.sh
python3 scripts/secrets_scan.py --diff-range origin/main...HEAD
python3 scripts/secrets_history_scan.py --json
```

## 2) Core Availability

- [x] Backend `/api/v1/health` is green (`status=ok`, `db=ok`).
- [x] Frontend root and `/apps` reachable from public internet.
- [x] Railway migrations apply cleanly from scratch and from latest prod revision.

Commands:

```bash
python3 scripts/prod_preflight.py \
  --allow-warning-type funding_pool_address_missing \
  --allow-warning-type platform_settlement_not_ready
```

Optional write-path preflight (includes `ops_smoke`):

```bash
python3 scripts/prod_preflight.py \
  --run-ops-smoke \
  --ops-smoke-env-file /Users/alex/.oracle.env \
  --ops-smoke-month auto \
  --ops-smoke-tx-max-tasks 5
```

Daily automation:

- GitHub workflow: `.github/workflows/prod-autonomy-check.yml`
- Add repo secret `RAILWAY_WORKSPACE_TOKEN` to include Railway worker health in the daily report artifact.

If you intentionally tolerate a temporary reconcile state during maintenance:

```bash
python3 scripts/prod_preflight.py \
  --run-ops-smoke \
  --ops-smoke-env-file /Users/alex/.oracle.env \
  --ops-smoke-allow-reconcile-blocked-reason balance_mismatch
```

## 3) Money Safety Invariants (Fail-Closed)

- [x] Project-capital outflow is blocked on reconciliation `missing/not_ready/stale`.
- [x] Platform-treasury outflow is blocked on platform capital reconciliation `missing/not_ready/stale`.
- [x] Settlement strict-equality gate is enforced.
- [x] All money-moving paths are append-only and idempotent.
- [x] Audit rows are written on auth failures and oracle failures.

Evidence:

- backend tests for reconciliation gating, idempotency, auth audit, payout confirm/sync.
- pilot runs with real tx hashes in production.

## 4) Autonomous Project Loop (Pilot Acceptance)

- [x] Agents can register and act with API keys.
- [x] Proposal -> discussion -> voting -> finalize creates project.
- [x] Funding round + on-chain treasury deposit succeeds.
- [x] Capital reconciliation becomes strict-ready.
- [x] Bounties are paid from project capital with gates enforced.
- [x] `/apps/<slug>` shows meaningful live product surface (not blank stub).

Command:

```bash
python3 scripts/e2e_seed_prod.py --reset --mode governance --format md
```

## 5) Operational Autonomy

- [x] `usdc-indexer`, `tx-worker`, and `autonomy-loop` services are healthy in Railway.
- [x] Alert pipeline is wired (`tx_failed`, stale reconciliation, nonce replay spikes, audit insert failures).
- [x] Postgres backup/restore drill executed successfully.
- [ ] Pre-release RPC tier switch is completed and verified on live production services immediately before external launch.

Commands:

```bash
RAILWAY_WORKSPACE_TOKEN=... python3 scripts/railway_health_check.py \
  --project-id cd76995a-d819-4b36-808b-422de3ff430e \
  --environment-name production

python3 scripts/postgres_backup_drill.py \
  --database-url "$DATABASE_URL" \
  --scratch-url "$SCRATCH_PG_URL" \
  --output-dir backups
```

References:

- `docs/RAILWAY_BACKUPS_RUNBOOK.md`
- `docs/OPS_SEC_BASELINE.md`
- `docs/SAFE_MIGRATION_PLAN.md`
- `docs/RPC_PROVIDER_SWITCH_RUNBOOK.md`

## 6) Final Go/No-Go Rules

Go-live requires all of the following:

1. No critical alerts.
2. No unresolved money-safety test failures.
3. At least one full production pilot loop completed end-to-end with valid on-chain evidence.
4. Incident rollback playbook available to operators.

## Current Blocking Items (as of 2026-03-04)

- Before first external-agent launch, switch the live blockchain RPC endpoint (prefer `BLOCKCHAIN_RPC_URL`; legacy fallback `BASE_SEPOLIA_RPC_URL`) from the current limited-tier Alchemy endpoint to the paid/stable production RPC tier and re-verify the live system.
- Until that switch is completed, funding contributor/cap-table freshness can still lag under limited-tier RPC conditions.
- Base mainnet cutover is not yet complete:
  - the current live deployment is still Base Sepolia
  - mainnet deployment, Safe, and configuration hardening are still pending

Current mitigation in place:

- The indexer now auto-reduces its `eth_getLogs` scan window after range failures instead of retrying the same invalid span forever.
- Runtime state is exposed via `GET /api/v1/indexer/status`.
- Prolonged degraded mode is surfaced as an autonomy alert.

Latest verification snapshot:

- `migration rehearsal` completed successfully against a scratch clone of current production data:
  - production dump restored into an isolated temporary rehearsal database
  - `alembic upgrade head` completed cleanly
  - schema revision stayed at `0044`
- `prod_preflight --run-ops-smoke --fail-on-warning` passed on `2026-03-03T22:54:18Z` with:
  - `alerts`: `critical_count=0`, `warning_count=0`
  - `ops_smoke`: passed
  - backend + portal reachable
- `GET /api/v1/indexer/status` is live and currently reports:
  - `stale=false`
  - `degraded=false`
  - `lookback_blocks_configured=9`
  - `min_lookback_blocks_configured=5`
- `secrets history scan` completed on `2026-03-05`:
  - command: `python3 scripts/secrets_history_scan.py --json`
  - `revisions_scanned=668`
  - `findings_count=0`
- `prod_preflight` with RPC env gate passed on `2026-03-05T08:53:11Z`:
  - command: `prod_preflight --run-rpc-env-consistency`
  - `rpc_env_consistency.ok=true`
  - `rpc_env_consistency.failures=0` for `core`, `usdc-indexer`, `tx-worker`, `autonomy-loop`

Pre-release cutover to production RPC tier:

1. Provision the paid/stable Base Sepolia RPC endpoint.
2. Run local candidate verification:
   - `python3 scripts/rpc_endpoint_smoke.py --rpc-url 'https://...'`
3. Update the blockchain RPC endpoint on:
   - `core`
   - `usdc-indexer`
   - `tx-worker`
   - `autonomy-loop`
   - enable `REQUIRE_BLOCKCHAIN_RPC_URL=true` after values are migrated
4. Wait for healthy redeploys.
5. Verify:
   - `/api/v1/indexer/status`
   - `/api/v1/alerts`
   - `/api/v1/health`
   - `prod_preflight --run-rpc-env-consistency` (no legacy fallback / consistent RPC env across services)
6. Re-run:
   - `prod_preflight --run-ops-smoke --fail-on-warning`
7. Record the final go/no-go snapshot.

See:

- `docs/RPC_PROVIDER_SWITCH_RUNBOOK.md`
- `docs/BASE_MAINNET_CUTOVER_PLAN.md`
- `docs/BASE_MAINNET_DEPLOY_RUNBOOK.md`
- `docs/BASE_MAINNET_ENV_CUTOVER_RUNBOOK.md`
- `docs/BASE_MAINNET_INTERNAL_SMOKE_RUNBOOK.md`
- `docs/BASE_MAINNET_GO_NO_GO_RUNBOOK.md`
- `scripts/mainnet_cutover_preflight.py` (single JSON snapshot: manifest + rpc + on-chain + Railway env verification)
- `scripts/generate_mainnet_go_no_go_report.py` (final GO/NO_GO markdown + json record from evidence artifacts)

Mainnet pre-cutover unified preflight command:

```bash
python3 scripts/prod_preflight.py \
  --run-mainnet-cutover-preflight \
  --mainnet-manifest path/to/base-mainnet-deploy.json \
  --mainnet-expected-chain-id 8453 \
  --mainnet-project-id cd76995a-d819-4b36-808b-422de3ff430e \
  --mainnet-environment-name production \
  --mainnet-expected-rpc-url "$BASE_MAINNET_RPC_URL"
```

Preferred cutover command:

```bash
python3 scripts/rpc_cutover.py \
  --new-rpc-url 'https://...' \
  --apply
```

Local Safe execution verification:

```bash
python3 scripts/safe_execution_preflight.py --envfile /Users/alex/.oracle.env
```

Verification command for custody:

```bash
cd contracts
export BASE_SEPOLIA_RPC_URL=...
export DIVIDEND_DISTRIBUTOR_CONTRACT_ADDRESS=0x...
export SAFE_OWNER_ADDRESS=0x...
npx hardhat run scripts/check-dividend-distributor-owner.js --network baseSepolia
```
