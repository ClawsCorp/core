# Oracle Automation Policy v1 (MVP → v1)

## Purpose
Define when the system may execute money-moving actions automatically and when it must fail-closed.

## Oracle Powers (high risk)
- Create/approve projects
- Create revenue/expense events (append-only)
- Run reconciliation
- Execute monthly payouts
- Pay bounties (USDC transfers)

## Separation of credentials
- ORACLE_API_KEY / ORACLE_HMAC_SECRET: admin API access (Railway secrets).
- ORACLE_SIGNER_PRIVATE_KEY: on-chain signer (Railway secrets).
- Never reuse agent api keys as oracle credentials.

## Oracle request authentication (required headers)
- `X-Request-Timestamp`: unix seconds.
- `X-Request-Id`: unique nonce per request (anti-replay).
- `X-Signature`: HMAC-SHA256 over `{timestamp}.{body_hash}`.

Behavior:
- Fail-closed on missing headers/signature (`403`).
- Timestamp freshness is enforced with TTL (default 300 seconds, plus small skew allowance); stale requests are rejected (`403`).
- Reusing `X-Request-Id` is rejected as replay (`409`).
- All oracle requests (accepted or rejected) must produce an `audit_logs` row with `signature_status` (`ok|invalid|stale|replay`).

## Default Mode (MVP)
- Eligibility can be automated.
- Transfers can be manual or limited automation.
- All actions must write audit_log with:
  actor_type=oracle, route, idempotency_key, body_hash, signature_status, tx_hash (if on-chain), timestamp.

## Auto-pay limits (recommended)
- AUTO_PAY_MAX_PER_BOUNTY = 50 USDC (micro-USDC)
- AUTO_PAY_DAILY_CAP = 200 USDC
- Any payment exceeding limits: require manual approval or multisig (future).

## Eligibility gates for bounty auto-pay
Auto-pay only if:
- bounty.status == eligible_for_payout
- PR merged AND required CI checks passed AND required approvals present
- claimant agent has verified wallet address on file
- idempotency key not used before for that bounty

## Profit deposit + payouts
- Profit deposit to DividendDistributor may be automated ONLY when:
  - settlement exists for profit_month_id
  - profit_sum_micro_usdc >= 0
  - reconciliation ready will become true AFTER deposit (i.e., deposit amount is exactly profit_sum)
- Historical payout metadata backfill may be performed with `POST /api/v1/oracle/payouts/{profit_month_id}/sync` only after reconciliation is ready and on-chain distribution is confirmed `distributed=true` (fail-closed recovery path).
- Payout execution may run automatically ONLY when:
  - latest reconciliation for profit_month_id has ready=true (STRICT EQUALITY)
  - recipients count within contract MAX limits
  - idempotency lock is acquired for that month (one execution)

## Fail-closed rules
- If any required check fails, do not proceed (ready=false, stop).
- If on-chain reads fail (RPC error), stop.
- If balances mismatch (delta != 0), stop.
- If recipients exceed MAX, stop.

## Incident response
- Immediately rotate oracle credentials on suspected compromise.
- Pause automation (feature flag).
- Publish post-mortem and remediation steps.

## Roadmap
- Move funds custody to Vault contracts.
- Move signer to multisig Safe.
- Add two-person rule for large actions.
