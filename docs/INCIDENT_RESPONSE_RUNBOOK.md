# Incident Response Runbook (Autonomy Loop)

Fail-closed procedure for money-moving incidents.

## Trigger Conditions

Run this playbook when one of these appears:
- `tx_outbox_failed` critical alerts
- repeated nonce replay/auth failures
- stale indexer/reconciliation during active money movement
- unexpected balance mismatch or unexplained transfers

## Phase 1: Contain (Immediate)

1. Pause writers:
- stop/scale down `autonomy-loop`
- stop/scale down `tx-worker`

2. Keep readers online:
- backend can stay up for visibility/public reads.

3. Preserve evidence:
- do not delete outbox/audit rows
- capture current alerts + recent logs

## Phase 2: Assess

1. Run read-only preflight:
```bash
python3 scripts/prod_preflight.py --timeout-seconds 20
```

2. Inspect alerts endpoint:
```bash
curl -sS https://core-production-b1a0.up.railway.app/api/v1/alerts | jq .
```

3. Classify incident type:
- auth/signature/replay
- tx submission/signer/rpc
- reconciliation/indexer drift
- data integrity/idempotency

## Phase 3: Recover

Apply targeted fix, then restart in order:
1. backend (if code/config changed)
2. tx-worker
3. autonomy-loop

Then run full write-path preflight:
```bash
python3 scripts/prod_preflight.py \
  --run-ops-smoke \
  --ops-smoke-env-file /Users/alex/.oracle.env \
  --ops-smoke-month auto \
  --ops-smoke-tx-max-tasks 3
```

## Phase 4: Verify Closure

All must hold:
- no critical alerts
- no stuck `processing` outbox tasks beyond threshold
- reconciliation/settlement state matches expected month outcome

## Post-Incident

Create a short postmortem with:
- timeline (UTC)
- root cause
- impacted subsystems
- corrective actions
- preventive action PR links
