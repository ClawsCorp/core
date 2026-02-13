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

Server-side only (not used directly by the runner):

- `ORACLE_SIGNER_PRIVATE_KEY` must be configured on backend for tx submission paths.

## Commands

Global flag:

- `--json`: print command result JSON to stdout (human-readable key/value output goes to stderr).

```bash
PYTHONPATH=src python -m oracle_runner reconcile --month 202601
PYTHONPATH=src python -m oracle_runner reconcile-project-capital --project-id proj_...
PYTHONPATH=src python -m oracle_runner evaluate-bounty-eligibility --bounty-id bty_... --payload /path/eligibility.json
PYTHONPATH=src python -m oracle_runner mark-bounty-paid --bounty-id bty_... --paid-tx-hash 0x...
PYTHONPATH=src python -m oracle_runner create-distribution --month 202601
PYTHONPATH=src python -m oracle_runner execute-distribution --month 202601 --payload /path/execute.json
PYTHONPATH=src python -m oracle_runner confirm-payout --month 202601 [--tx-hash 0x...]
PYTHONPATH=src python -m oracle_runner sync-payout --month 202601 [--tx-hash 0x...]
PYTHONPATH=src python -m oracle_runner run-month --month 202601 --execute-payload /path/execute.json
PYTHONPATH=src python -m oracle_runner --json reconcile --month 202601
PYTHONPATH=src python -m oracle_runner --json reconcile-project-capital --project-id proj_...
PYTHONPATH=src python -m oracle_runner --json evaluate-bounty-eligibility --bounty-id bty_... --payload /path/eligibility.json
PYTHONPATH=src python -m oracle_runner --json mark-bounty-paid --bounty-id bty_... --paid-tx-hash 0x...
```

`run-month` always prints exactly one JSON summary object to stdout (pipeline-friendly).

`execute-distribution` validates payload shape locally:

- required keys: `stakers`, `staker_shares`, `authors`, `author_shares`
- list lengths must match (`stakers` vs `staker_shares`, `authors` vs `author_shares`)
- addresses must be non-empty strings
- shares must be positive integers

If `--idempotency-key` is omitted for execute actions, runner derives deterministic key:

- `execute_distribution:{month}:{sha256(canonical_json)}`

## `run-month` exit codes

- `0`: complete (or payout already finalized)
- `2`: reconciliation not ready
- `3`: create-distribution blocked
- `4`: execute-distribution blocked
- `5`: confirm-payout is still pending
- `1`: runner/config/request error

## Security and safety notes

- Every write call sends `X-Request-Timestamp`, `X-Request-Id`, `X-Signature`.
- Signature payload format is exactly:
  - `{timestamp}.{request_id}.{method}.{path}.{body_hash}`
- `body_hash = sha256(raw_request_body_bytes).hexdigest()`.
- A fresh `request_id` and timestamp are generated for every call.
- `Idempotency-Key` header is sent for execute calls (explicit or deterministic).
- Runner does **not** log HMAC secret, signed payload, or signature.
