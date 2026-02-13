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
        <p>Use oracle runner to reconcile, create/execute distribution, confirm payout, sync payouts:</p>
        <pre style={{ whiteSpace: "pre-wrap", wordBreak: "break-word" }}>
{`PYTHONPATH=src python -m oracle_runner reconcile --month YYYYMM
PYTHONPATH=src python -m oracle_runner create-distribution --month YYYYMM
PYTHONPATH=src python -m oracle_runner execute-distribution --month YYYYMM --payload execute.json
PYTHONPATH=src python -m oracle_runner confirm-payout --month YYYYMM
PYTHONPATH=src python -m oracle_runner sync-payout --month YYYYMM
PYTHONPATH=src python -m oracle_runner run-month --month YYYYMM --execute-payload execute.json`}
        </pre>
      </DataCard>
    </PageContainer>
  );
}
