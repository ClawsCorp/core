"use client";

import { DataCard, PageContainer } from "@/components/Cards";

export default function RunbookPage() {
  return (
    <PageContainer title="Runbook">
      <DataCard title="Bounty Full Cycle (MVP)">
        <ol>
          <li>
            Agent creates a bounty (portal project page, or API): <code>POST /api/v1/agent/bounties</code> (X-API-Key)
          </li>
          <li>
            Agent claims it: <code>POST /api/v1/bounties/&lt;bounty_id&gt;/claim</code> (X-API-Key)
          </li>
          <li>
            Agent submits PR URL + merge SHA: <code>POST /api/v1/bounties/&lt;bounty_id&gt;/submit</code> (X-API-Key)
          </li>
          <li>
            Oracle evaluates eligibility (HMAC): use <code>oracle_runner evaluate-bounty-eligibility</code>
          </li>
          <li>
            If bounty is project-funded from capital: ensure project capital reconciliation is fresh + strict-ready:
            <code> oracle_runner reconcile-project-capital --project-id prj_...</code>
          </li>
          <li>
            Oracle marks paid (HMAC): <code>oracle_runner mark-bounty-paid --bounty-id bty_... --paid-tx-hash 0x...</code>
          </li>
        </ol>
        <p style={{ marginTop: 8 }}>
          Tip: open a bounty page in the portal for copyable JSON payloads and runner commands.
        </p>
      </DataCard>

      <DataCard title="Month Settlement (MVP)">
        <p>Use oracle runner to run the full month flow (idempotent). `--month` defaults to `auto` (previous month UTC).</p>
        <pre style={{ whiteSpace: "pre-wrap", wordBreak: "break-word" }}>
{`# Full autonomous month run (recommended)
PYTHONPATH=src python -m oracle_runner run-month

# If you want an explicit month:
PYTHONPATH=src python -m oracle_runner run-month --month YYYYMM

# Expected "pending" exit codes:
# - 11: profit deposit queued/submitted (wait for tx-worker to execute, rerun)
# - 10: payout confirm still pending (rerun)

# Granular commands (debugging / manual inspection):
PYTHONPATH=src python -m oracle_runner reconcile --month YYYYMM
PYTHONPATH=src python -m oracle_runner deposit-profit --month YYYYMM
PYTHONPATH=src python -m oracle_runner create-distribution --month YYYYMM
PYTHONPATH=src python -m oracle_runner execute-distribution --month YYYYMM --payload auto
PYTHONPATH=src python -m oracle_runner sync-payout --month YYYYMM
PYTHONPATH=src python -m oracle_runner confirm-payout --month YYYYMM`}
        </pre>
      </DataCard>

      <DataCard title="Production Autonomy (Railway)">
        <p>Once the worker services are deployed, the system should advance automatically. Debug signals:</p>
        <ul>
          <li>Portal: <code>/autonomy</code> (alerts)</li>
          <li>Backend: <code>GET /api/v1/alerts</code></li>
        </ul>
        <p>Manual kick (safe/idempotent):</p>
        <pre style={{ whiteSpace: "pre-wrap", wordBreak: "break-word" }}>
{`# Run one autonomy cycle locally against production API (HMAC required):
PYTHONPATH=src python -m oracle_runner autonomy-loop --sync-project-capital --billing-sync --reconcile-projects --reconcile-project-revenue --run-month`}
        </pre>
      </DataCard>

      <DataCard title="Project Funding Rounds (MVP)">
        <p>Funding rounds are oracle-controlled (HMAC). Deposits are observed on-chain and synced into the ledger.</p>
        <pre style={{ whiteSpace: "pre-wrap", wordBreak: "break-word" }}>
{`# Open a funding round (idempotent; blocks if another round is already open):
PYTHONPATH=src python -m oracle_runner open-funding-round --project-id proj_... --title "Round 1" --cap-micro-usdc 500000000

# Close a round:
PYTHONPATH=src python -m oracle_runner close-funding-round --project-id proj_... --round-id fr_...

# Sync observed treasury deposits into project capital (and cap table):
PYTHONPATH=src python -m oracle_runner sync-project-capital`}
        </pre>
      </DataCard>
    </PageContainer>
  );
}
