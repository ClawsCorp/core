# Oracle Runner v1

`oracle_runner` is an autonomous CLI for month lifecycle orchestration over Oracle HMAC v2 protected endpoints.

## Location

- Module: `backend/src/oracle_runner`
- Entrypoint: `python -m oracle_runner ...` (run from `backend` with `PYTHONPATH=src`)

## Required environment variables

- `ORACLE_BASE_URL` (example: `https://core-production-...railway.app`)
- `ORACLE_HMAC_SECRET`

Optional warning/ops context variables:

- `ORACLE_REQUEST_TTL_SECONDS`
- `ORACLE_CLOCK_SKEW_SECONDS`
- `ORACLE_AUTO_MONTH` (optional; if set, must be `YYYYMM` and overrides `--month auto` resolution)

Server-side only (not used directly by the runner):

- If the backend submits tx inline (legacy mode), it requires `ORACLE_SIGNER_PRIVATE_KEY`.
- If `TX_OUTBOX_ENABLED=true` on the backend, tx submission is expected to run out-of-band via `tx-worker` (see below).

`tx-worker` environment variables (runs locally, sends tx):

- `BASE_SEPOLIA_RPC_URL`
- `USDC_ADDRESS`
- `DIVIDEND_DISTRIBUTOR_CONTRACT_ADDRESS`
- `FUNDING_POOL_CONTRACT_ADDRESS` (optional; enables staker recipient generation from observed transfers)
- `ORACLE_SIGNER_PRIVATE_KEY`
- `SAFE_OWNER_ADDRESS` (optional; when set, owner-only distribution txs must route through Safe)
- `SAFE_OWNER_KEYS_FILE` (optional, local-only; JSON file with Safe owner keys for testnet automation)
- `CONTRACTS_DIR` (optional)

`tx-worker` processes tx outbox task types:
- `deposit_profit`
- `deposit_marketing_fee`
- `create_distribution`
- `execute_distribution`

Safe behavior for owner-only distribution tasks:

- If `SAFE_OWNER_ADDRESS` is set and `SAFE_OWNER_KEYS_FILE` is not set, `create_distribution` / `execute_distribution` fail-closed into `blocked` with `safe_execution_required` and include machine-readable Safe calldata in task result.
- If both `SAFE_OWNER_ADDRESS` and `SAFE_OWNER_KEYS_FILE` are set, local `tx-worker` can execute the Safe transaction directly (testnet automation mode) and then record the resulting on-chain tx hash back into the backend.
- `SAFE_OWNER_KEYS_FILE` must stay local and must never be committed to the repo or stored in Railway/Vercel secrets.
- Before running local Safe execution, run:
  - `python3 scripts/safe_execution_preflight.py --envfile /Users/alex/.oracle.env`
- See `docs/SAFE_EXECUTION_RUNBOOK.md` for the full operator procedure.

`git-worker` environment variables (runs locally, applies git tasks):

- `DAO_GIT_REPO_DIR` (optional; clean repo root/worktree with `scripts/new_product_surface.mjs`)

`git-worker` currently supports:

- `create_app_surface_commit` -> generates `frontend/src/product_surfaces/<slug>.tsx` + registry update
- `create_project_backend_artifact_commit` -> generates `backend/src/project_artifacts/<slug>.py`

Git task PR policy:

- `open_pr=true` means the task must produce a real `pr_url`; otherwise the task fails fail-closed.
- `auto_merge=true` means `git-worker` will run GitHub auto-merge (`gh pr merge --auto --merge --delete-branch`) after PR creation.
- `auto_merge=true` requires `open_pr=true`; otherwise enqueue is rejected.
- `auto_merge=true` now uses an explicit merge policy recorded in task payload/result:
  - `merge_policy.required_checks`
  - `merge_policy.required_approvals`
  - `merge_policy.require_non_draft`
- Fail-closed behavior:
  - if a required check name is missing from the PR check list, the task fails
- if any required check is already failed/cancelled, the task fails
- if `required_approvals > 0` and the PR is not `APPROVED`, the task fails
- if the PR is draft and `require_non_draft=true`, the task fails
- Agent enqueue endpoints default DAO auto-merge tasks to a stable required-check set:
  - `api-types`, `backend`, `contracts`, `dependency-review`, `frontend`, `secrets-scan`

## Commands

Global flag:

- `--json`: print command result JSON to stdout (human-readable key/value output goes to stderr).

```bash
PYTHONPATH=src python -m oracle_runner reconcile --month 202601
PYTHONPATH=src python -m oracle_runner reconcile-project-capital --project-id proj_...
PYTHONPATH=src python -m oracle_runner reconcile-project-revenue --project-id proj_...
PYTHONPATH=src python -m oracle_runner project-reconcile --project-id proj_...
PYTHONPATH=src python -m oracle_runner sync-project-capital
PYTHONPATH=src python -m oracle_runner billing-sync
PYTHONPATH=src python -m oracle_runner prune-operational-tables
PYTHONPATH=src python -m oracle_runner run-project-month --project-id proj_...
PYTHONPATH=src python -m oracle_runner project-capital-event --project-id proj_... --delta-micro-usdc 1000000 --source stake
PYTHONPATH=src python -m oracle_runner open-funding-round --project-id proj_... --title "Round 1" --cap-micro-usdc 500000000
PYTHONPATH=src python -m oracle_runner close-funding-round --project-id proj_... --round-id fr_...
PYTHONPATH=src python -m oracle_runner evaluate-bounty-eligibility --bounty-id bty_... --payload /path/eligibility.json
PYTHONPATH=src python -m oracle_runner mark-bounty-paid --bounty-id bty_... --paid-tx-hash 0x...
PYTHONPATH=src python -m oracle_runner create-distribution --month 202601
PYTHONPATH=src python -m oracle_runner build-execute-payload --month 202601 --out /path/execute.json
PYTHONPATH=src python -m oracle_runner execute-distribution --month 202601 --payload /path/execute.json
PYTHONPATH=src python -m oracle_runner execute-distribution --month 202601 --payload auto
PYTHONPATH=src python -m oracle_runner confirm-payout --month 202601 [--tx-hash 0x...]
PYTHONPATH=src python -m oracle_runner sync-payout --month 202601 [--tx-hash 0x...]
PYTHONPATH=src python -m oracle_runner marketing-deposit
PYTHONPATH=src python -m oracle_runner run-month --execute-payload auto
PYTHONPATH=src python -m oracle_runner run-month --month 202601 --execute-payload /path/execute.json
PYTHONPATH=src python -m oracle_runner tx-worker --max-tasks 10
PYTHONPATH=src python -m oracle_runner tx-worker --loop --max-tasks 10
PYTHONPATH=src python -m oracle_runner git-worker --max-tasks 5
PYTHONPATH=src python -m oracle_runner git-worker --loop --max-tasks 5 --repo-dir /path/to/repo
PYTHONPATH=src python -m oracle_runner autonomy-loop --loop
PYTHONPATH=src python -m oracle_runner autonomy-loop --loop --sync-project-capital --reconcile-projects --run-month
PYTHONPATH=src python -m oracle_runner autonomy-loop --loop --sync-project-capital --reconcile-projects --run-month --prune-operational-tables

# Enable these only when the corresponding flows are active:
#   --billing-sync
#   --reconcile-project-revenue
#   --marketing-deposit
# `--prune-operational-tables` is safe to keep enabled in long-running loops; it only deletes old non-ledger operational rows.
PYTHONPATH=src python -m oracle_runner --json reconcile --month 202601
PYTHONPATH=src python -m oracle_runner --json reconcile-project-capital --project-id proj_...
PYTHONPATH=src python -m oracle_runner --json project-reconcile --project-id proj_...
PYTHONPATH=src python -m oracle_runner --json open-funding-round --project-id proj_...
PYTHONPATH=src python -m oracle_runner --json sync-project-capital
PYTHONPATH=src python -m oracle_runner --json prune-operational-tables
PYTHONPATH=src python -m oracle_runner --json project-capital-event --project-id proj_... --delta-micro-usdc 1000000 --source stake
PYTHONPATH=src python -m oracle_runner --json evaluate-bounty-eligibility --bounty-id bty_... --payload /path/eligibility.json
PYTHONPATH=src python -m oracle_runner --json mark-bounty-paid --bounty-id bty_... --paid-tx-hash 0x...
PYTHONPATH=src python -m oracle_runner --json marketing-deposit
```

`run-month` always prints exactly one JSON summary object to stdout (pipeline-friendly).

`run-month` month selection:

- default `--month auto` (previous month in UTC)
- to override for deterministic runs/tests: set `ORACLE_AUTO_MONTH=YYYYMM`

`execute-distribution` validates payload shape locally:

- required keys: `stakers`, `staker_shares`, `authors`, `author_shares`
- list lengths must match (`stakers` vs `staker_shares`, `authors` vs `author_shares`)
- addresses must be non-empty strings
- shares must be positive integers

If `--idempotency-key` is omitted for execute actions, runner derives deterministic key:

- `execute_distribution:{month}:{sha256(canonical_json)}`

## One-command ops smoke

For a single operational check of indexer ingestion + tx-worker + reconciliation + alerts:

```bash
scripts/ops_smoke.sh --env-file /Users/alex/.oracle.env --month auto --tx-max-tasks 5
```

See `docs/OPS_SMOKE_RUNBOOK.md` for details.
GitHub manual run is available via workflow `ops-smoke` (`.github/workflows/ops-smoke.yml`).
By default, `ops_smoke` fails when reconciliation is not strict-ready; temporary allowlist is supported via `--allow-reconcile-blocked-reason` or `OPS_SMOKE_ALLOW_RECON_BLOCKED`.
When `--month auto` is used, `ops_smoke` resolves month from `/api/v1/settlement/months` preferring latest strict-ready month (`ready=true`, `delta=0`), then falls back to latest row.

## `run-month` exit codes

- `0`: complete (or payout already finalized)
- `4`: reconciliation blocked (not ready)
- `6`: create-distribution blocked
- `7`: execute payload generation blocked
- `9`: execute-distribution blocked
- `10`: confirm-payout is still pending
- `11`: profit deposit was submitted/queued; rerun later once tx-worker executes it
- `1`: runner/config/request error (incl. network/auth)

## Security and safety notes

- Every write call sends `X-Request-Timestamp`, `X-Request-Id`, `X-Signature`.
- Signature payload format is exactly:
  - `{timestamp}.{request_id}.{method}.{path}.{body_hash}`
- `body_hash = sha256(raw_request_body_bytes).hexdigest()`.
- A fresh `request_id` and timestamp are generated for every call.
- `Idempotency-Key` header is sent for execute calls (explicit or deterministic).
- Runner does **not** log HMAC secret, signed payload, or signature.
