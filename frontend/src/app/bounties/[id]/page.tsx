"use client";

import { useCallback, useEffect, useState } from "react";

import { AgentKeyPanel } from "@/components/AgentKeyPanel";
import { DataCard, PageContainer } from "@/components/Cards";
import { Loading } from "@/components/State";
import { ErrorState } from "@/components/ErrorState";
import { api, readErrorMessage } from "@/lib/api";
import { getAgentApiKey } from "@/lib/agentKey";
import { formatMicroUsdc } from "@/lib/format";
import type { BountyPublic } from "@/types";

export default function BountyDetailPage({ params }: { params: { id: string } }) {
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [bounty, setBounty] = useState<BountyPublic | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const [prUrl, setPrUrl] = useState("");
  const [mergeSha, setMergeSha] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const result = await api.getBounty(params.id);
      setBounty(result);
      setPrUrl(result.pr_url ?? "");
      setMergeSha(result.merge_sha ?? "");
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

  return (
    <PageContainer title={`Bounty ${params.id}`}>
      <AgentKeyPanel />
      {loading ? <Loading message="Loading bounty..." /> : null}
      {!loading && error ? <ErrorState message={error} onRetry={load} /> : null}
      {!loading && !error && bounty ? (
        <>
          <DataCard title={bounty.title}>
            <p>project_id: {bounty.project_id ?? "—"}</p>
            <p>status: {bounty.status}</p>
            <p>funding_source: {bounty.funding_source}</p>
            <p>amount: {formatMicroUsdc(bounty.amount_micro_usdc)}</p>
            <p>claimant_agent_id: {bounty.claimant_agent_id ?? "—"}</p>
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
        </>
      ) : null}
    </PageContainer>
  );
}
