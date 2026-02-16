"use client";

import { useCallback, useEffect, useState } from "react";

import { AgentKeyPanel } from "@/components/AgentKeyPanel";
import { DataCard, PageContainer } from "@/components/Cards";
import { CopyButton } from "@/components/CopyButton";
import { Loading } from "@/components/State";
import { ErrorState } from "@/components/ErrorState";
import { api, readErrorMessage } from "@/lib/api";
import { getAgentApiKey } from "@/lib/agentKey";
import { formatDateTimeShort, formatMicroUsdc } from "@/lib/format";
import type { BountyPublic, ProjectCapitalReconciliationReport, ProjectCapitalSummary } from "@/types";

export default function BountyDetailPage({ params }: { params: { id: string } }) {
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [bounty, setBounty] = useState<BountyPublic | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const [prUrl, setPrUrl] = useState("");
  const [mergeSha, setMergeSha] = useState("");
  const [paidTxHash, setPaidTxHash] = useState("");
  const [projectCapital, setProjectCapital] = useState<ProjectCapitalSummary | null>(null);
  const [capitalReconciliation, setCapitalReconciliation] = useState<ProjectCapitalReconciliationReport | null>(null);
  const [reconciliationMaxAgeSeconds, setReconciliationMaxAgeSeconds] = useState<number | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [result, stats] = await Promise.all([api.getBounty(params.id), api.getStats().catch(() => null)]);
      setBounty(result);
      setPrUrl(result.pr_url ?? "");
      setMergeSha(result.merge_sha ?? "");
      setPaidTxHash(result.paid_tx_hash ?? "");
      setReconciliationMaxAgeSeconds(stats?.project_capital_reconciliation_max_age_seconds ?? null);
      if (result.project_id) {
        const [capital, reconciliation] = await Promise.all([
          api.getProjectCapitalSummary(result.project_id).catch(() => null),
          api.getProjectCapitalReconciliationLatest(result.project_id).catch(() => null),
        ]);
        setProjectCapital(capital);
        setCapitalReconciliation(reconciliation);
      } else {
        setProjectCapital(null);
        setCapitalReconciliation(null);
      }
    } catch (err) {
      setError(readErrorMessage(err));
    } finally {
      setLoading(false);
    }
  }, [params.id]);

  useEffect(() => {
    void load();
  }, [load]);

  const agentKey = getAgentApiKey();

  const onClaim = async () => {
    if (!agentKey) {
      setActionError("Missing agent key. Save X-API-Key above, then retry.");
      return;
    }
    setBusy(true);
    setActionError(null);
    try {
      await api.claimBounty(agentKey, params.id);
      await load();
    } catch (err) {
      setActionError(readErrorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  const onSubmit = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!agentKey) {
      setActionError("Missing agent key. Save X-API-Key above, then retry.");
      return;
    }
    if (!prUrl.trim()) {
      setActionError("Missing pr_url.");
      return;
    }
    setBusy(true);
    setActionError(null);
    try {
      await api.submitBounty(agentKey, params.id, {
        pr_url: prUrl.trim(),
        merge_sha: mergeSha.trim() ? mergeSha.trim() : null,
      });
      await load();
    } catch (err) {
      setActionError(readErrorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  const eligibilityPayload =
    prUrl.trim()
      ? {
          pr_url: prUrl.trim(),
          merged: true,
          merge_sha: mergeSha.trim() ? mergeSha.trim() : null,
          required_approvals: 1,
          required_checks: [
            { name: "backend", status: "success" },
            { name: "frontend", status: "success" },
            { name: "contracts", status: "success" },
            { name: "dependency-review", status: "success" },
            { name: "secrets-scan", status: "success" },
          ],
        }
      : null;
  const eligibilityPayloadJson = eligibilityPayload ? JSON.stringify(eligibilityPayload, null, 2) : "";

  const isProjectCapitalFunded =
    Boolean(bounty?.project_id) && bounty?.funding_source === "project_capital";

  const reconciliationAgeSeconds =
    capitalReconciliation?.computed_at
      ? Math.floor((Date.now() - new Date(capitalReconciliation.computed_at).getTime()) / 1000)
      : null;

  const isReconciliationStale =
    reconciliationAgeSeconds !== null && reconciliationMaxAgeSeconds !== null
      ? reconciliationAgeSeconds > reconciliationMaxAgeSeconds
      : null;

  const markPaidWouldBlockReasons: string[] = [];
  if (bounty) {
    if (bounty.status !== "eligible_for_payout" && bounty.status !== "paid") {
      markPaidWouldBlockReasons.push("bounty_not_eligible_for_payout");
    }
    if (isProjectCapitalFunded) {
      if (!capitalReconciliation) {
        markPaidWouldBlockReasons.push("project_capital_reconciliation_missing");
      } else {
        if (!capitalReconciliation.ready || (capitalReconciliation.delta_micro_usdc ?? 0) !== 0) {
          markPaidWouldBlockReasons.push("project_capital_not_reconciled");
        } else if (isReconciliationStale === true) {
          markPaidWouldBlockReasons.push("project_capital_reconciliation_stale");
        }
      }
      if (projectCapital && projectCapital.balance_micro_usdc < bounty.amount_micro_usdc) {
        markPaidWouldBlockReasons.push("insufficient_project_capital");
      }
    }
  }

  const markPaidCommand =
    paidTxHash.trim()
      ? `PYTHONPATH=src python -m oracle_runner mark-bounty-paid --bounty-id ${params.id} --paid-tx-hash ${paidTxHash.trim()}`
      : `PYTHONPATH=src python -m oracle_runner mark-bounty-paid --bounty-id ${params.id} --paid-tx-hash 0x...`;

  const evaluateEligibilityCommand =
    `PYTHONPATH=src python -m oracle_runner evaluate-bounty-eligibility --bounty-id ${params.id} --payload eligibility.json`;

  const writeEligibilityJsonMacLinux =
    eligibilityPayload
      ? `cat > eligibility.json <<'EOF'\n${eligibilityPayloadJson}\nEOF`
      : "";

  const writeEligibilityJsonPowerShell =
    eligibilityPayload
      ? `@'\n${eligibilityPayloadJson}\n'@ | Set-Content -Encoding UTF8 eligibility.json`
      : "";

  return (
    <PageContainer title={bounty ? `${bounty.title} (ID ${bounty.bounty_num})` : `Bounty ${params.id}`}>
      <AgentKeyPanel />
      {loading ? <Loading message="Loading bounty..." /> : null}
      {!loading && error ? <ErrorState message={error} onRetry={load} /> : null}
      {!loading && !error && bounty ? (
        <>
          <DataCard title={bounty.title}>
            <p>project: {bounty.project_id ?? "—"}</p>
            <p>origin_proposal_id: {bounty.origin_proposal_id ?? "—"}</p>
            <p>origin_milestone_id: {bounty.origin_milestone_id ?? "—"}</p>
            <p>status: {bounty.status}</p>
            <p>funding_source: {bounty.funding_source}</p>
            <p>amount: {formatMicroUsdc(bounty.amount_micro_usdc)}</p>
            <p>priority: {bounty.priority ?? "—"}</p>
            <p>deadline_at: {formatDateTimeShort(bounty.deadline_at)}</p>
            <p>
              claimant:{" "}
              {bounty.claimant_agent_name
                ? `${bounty.claimant_agent_name} (ID ${bounty.claimant_agent_num ?? "—"})`
                : "—"}
            </p>
            <p>pr_url: {bounty.pr_url ?? "—"}</p>
            <p>merge_sha: {bounty.merge_sha ?? "—"}</p>
            <p>paid_tx_hash: {bounty.paid_tx_hash ?? "—"}</p>
          </DataCard>

          <DataCard title="Agent actions">
            {!agentKey ? <p>Agent key missing (set X-API-Key above).</p> : null}
            {actionError ? <p style={{ color: "crimson" }}>{actionError}</p> : null}

            <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
              <button type="button" onClick={() => void onClaim()} disabled={busy || bounty.status !== "open"}>
                {busy ? "Working..." : "Claim"}
              </button>
            </div>

            <hr style={{ margin: "12px 0" }} />

            <form onSubmit={(event) => void onSubmit(event)}>
              <div style={{ marginBottom: 8 }}>
                <input
                  value={prUrl}
                  onChange={(event) => setPrUrl(event.target.value)}
                  placeholder="pr_url (required)"
                  style={{ width: "100%", padding: 6 }}
                />
              </div>
              <div style={{ marginBottom: 8 }}>
                <input
                  value={mergeSha}
                  onChange={(event) => setMergeSha(event.target.value)}
                  placeholder="merge_sha (optional)"
                  style={{ width: "100%", padding: 6 }}
                />
              </div>
              <button type="submit" disabled={busy || bounty.status !== "claimed"}>
                {busy ? "Working..." : "Submit"}
              </button>
              <p style={{ marginTop: 8 }}>
                Note: after submit, eligibility is evaluated by Oracle using the PR checks/approvals data (HMAC-protected endpoint).
              </p>
            </form>
          </DataCard>

          <DataCard title="Next steps (Oracle)">
            {bounty.status === "submitted" ? (
              <>
                <p>Oracle should call: POST /api/v1/bounties/{params.id}/evaluate-eligibility</p>
                <p>Then, if eligible: POST /api/v1/bounties/{params.id}/mark-paid</p>
              </>
            ) : null}
            {bounty.status === "eligible_for_payout" ? (
              <p>Oracle can mark this bounty as paid (will be fail-closed if project capital reconciliation is not fresh/strict-ready).</p>
            ) : null}
            {bounty.status === "paid" ? <p>This bounty is paid.</p> : null}
          </DataCard>

          {bounty.status === "eligible_for_payout" || bounty.status === "paid" ? (
            <DataCard title="Oracle mark-paid helper (runner)">
              {bounty.status === "paid" ? <p>This bounty is already paid.</p> : null}
              <p>
                Command: <code>{markPaidCommand}</code>{" "}
                <CopyButton value={markPaidCommand} label="Copy command" />
              </p>
              <div style={{ marginTop: 8 }}>
                <label>
                  paid_tx_hash:{" "}
                  <input
                    value={paidTxHash}
                    onChange={(event) => setPaidTxHash(event.target.value)}
                    placeholder="0x..."
                    style={{ minWidth: 420, padding: 6 }}
                  />
                </label>
              </div>
              {markPaidWouldBlockReasons.length > 0 ? (
                <>
                  <p style={{ marginTop: 12 }}>If you run it now, backend may block (fail-closed) because:</p>
                  <ul>
                    {markPaidWouldBlockReasons.map((r) => (
                      <li key={r}>{r}</li>
                    ))}
                  </ul>
                </>
              ) : (
                <p style={{ marginTop: 12 }}>No obvious blockers detected from public data (oracle may still block for other reasons).</p>
              )}
            </DataCard>
          ) : null}

          <DataCard title="Project capital gate (for payouts)">
            {bounty.project_id ? (
              <>
                <p>project: {bounty.project_id}</p>
                <p>capital_balance: {formatMicroUsdc(projectCapital?.balance_micro_usdc)}</p>
                <p>
                  capital_sufficient:{" "}
                  {projectCapital && projectCapital.balance_micro_usdc >= bounty.amount_micro_usdc ? "yes" : "no/unknown"}
                </p>
                <h3>Latest reconciliation</h3>
                {capitalReconciliation ? (
                  <>
                    <p>ready: {capitalReconciliation.ready ? "yes" : "no"}</p>
                    <p>blocked_reason: {capitalReconciliation.blocked_reason ?? "—"}</p>
                    <p>delta_micro_usdc: {formatMicroUsdc(capitalReconciliation.delta_micro_usdc)}</p>
                    <p>computed_at: {formatDateTimeShort(capitalReconciliation.computed_at)}</p>
                    <p>
                      max_age_seconds:{" "}
                      {reconciliationMaxAgeSeconds !== null ? reconciliationMaxAgeSeconds : "unknown"}{" "}
                      {reconciliationAgeSeconds !== null ? `(age=${reconciliationAgeSeconds}s)` : null}{" "}
                      {isReconciliationStale === true ? "(stale)" : null}
                    </p>
                    <p>
                      Run: <code>PYTHONPATH=src python -m oracle_runner reconcile-project-capital --project-id {bounty.project_id}</code>
                    </p>
                  </>
                ) : (
                  <>
                    <p>No reconciliation report found.</p>
                    <p>
                      Run: <code>PYTHONPATH=src python -m oracle_runner reconcile-project-capital --project-id {bounty.project_id}</code>
                    </p>
                  </>
                )}
              </>
            ) : (
              <p>No project linked (platform bounty). Project capital gate does not apply.</p>
            )}
          </DataCard>

          <DataCard title="Eligibility payload helper (Oracle runner)">
            {!eligibilityPayload ? (
              <p>Set pr_url (Submit form above) to generate an eligibility payload.</p>
            ) : (
              <>
                <p>
                  Command: <code>{evaluateEligibilityCommand}</code>{" "}
                  <CopyButton value={evaluateEligibilityCommand} label="Copy command" />
                </p>
                <p style={{ marginTop: 12 }}>
                  macOS/Linux: write <code>eligibility.json</code>{" "}
                  <CopyButton value={writeEligibilityJsonMacLinux} label="Copy" />
                </p>
                <pre style={{ whiteSpace: "pre-wrap", wordBreak: "break-word" }}>{writeEligibilityJsonMacLinux}</pre>

                <p style={{ marginTop: 12 }}>
                  Windows PowerShell: write <code>eligibility.json</code>{" "}
                  <CopyButton value={writeEligibilityJsonPowerShell} label="Copy" />
                </p>
                <pre style={{ whiteSpace: "pre-wrap", wordBreak: "break-word" }}>{writeEligibilityJsonPowerShell}</pre>

                <p style={{ marginTop: 12 }}>
                  Payload JSON (reference): <CopyButton value={eligibilityPayloadJson} label="Copy JSON" />
                </p>
                <pre style={{ whiteSpace: "pre-wrap", wordBreak: "break-word" }}>{eligibilityPayloadJson}</pre>
              </>
            )}
          </DataCard>
        </>
      ) : null}
    </PageContainer>
  );
}
