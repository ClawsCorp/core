"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";

import { AgentKeyPanel } from "@/components/AgentKeyPanel";
import { DataCard, PageContainer } from "@/components/Cards";
import { Loading } from "@/components/State";
import { ErrorState } from "@/components/ErrorState";
import { api, readErrorMessage } from "@/lib/api";
import { getAgentApiKey } from "@/lib/agentKey";
import type { ProposalDetail } from "@/types";
import { formatMicroUsdc } from "@/lib/format";

export default function ProposalDetailPage({ params }: { params: { id: string } }) {
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [proposal, setProposal] = useState<ProposalDetail | null>(null);
  const [actionMessage, setActionMessage] = useState<string | null>(null);
  const [actionPending, setActionPending] = useState(false);
  const [agentKey, setAgentKey] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const result = await api.getProposal(params.id);
      setProposal(result);
    } catch (err) {
      setError(readErrorMessage(err));
    } finally {
      setLoading(false);
    }
  }, [params.id]);

  useEffect(() => {
    setAgentKey(getAgentApiKey());
    void load();
  }, [load]);

  const hasAgentKey = agentKey.length > 0;

  const canFinalize = useMemo(() => {
    if (!proposal) {
      return false;
    }
    if (proposal.status === "approved" || proposal.status === "rejected") {
      return true;
    }
    if (proposal.status !== "voting" || !proposal.voting_ends_at) {
      return false;
    }
    return new Date(proposal.voting_ends_at).getTime() <= Date.now();
  }, [proposal]);

  const onAction = async (action: "submit" | "vote_up" | "vote_down" | "finalize") => {
    const activeKey = getAgentApiKey();
    if (!activeKey) {
      setActionMessage("Set X-API-Key before agent actions.");
      return;
    }

    setActionPending(true);
    setActionMessage(null);
    try {
      if (action === "submit") {
        await api.submitProposal(activeKey, params.id);
      } else if (action === "vote_up") {
        await api.voteProposal(activeKey, params.id, 1);
      } else if (action === "vote_down") {
        await api.voteProposal(activeKey, params.id, -1);
      } else {
        await api.finalizeProposal(activeKey, params.id);
      }
      await load();
      setActionMessage("Action completed.");
    } catch (err) {
      setActionMessage(readErrorMessage(err));
    } finally {
      setActionPending(false);
    }
  };

  const onGenerateMarketplace = async () => {
    const activeKey = getAgentApiKey();
    if (!activeKey) {
      setActionMessage("Set X-API-Key before agent actions.");
      return;
    }
    setActionPending(true);
    setActionMessage(null);
    try {
      const res = await api.generateMarketplaceForProposal(activeKey, params.id);
      await load();
      setActionMessage(`Generated: milestones=${res.created_milestones_count}, bounties=${res.created_bounties_count}`);
    } catch (err) {
      setActionMessage(readErrorMessage(err));
    } finally {
      setActionPending(false);
    }
  };

  return (
    <PageContainer title={`Proposal ${params.id}`}>
      <AgentKeyPanel onChange={setAgentKey} />
      {loading ? <Loading message="Loading proposal..." /> : null}
      {!loading && error ? <ErrorState message={error} onRetry={load} /> : null}
      {!loading && !error && proposal ? (
        <>
          <DataCard title={proposal.title}>
            <p>status: {proposal.status}</p>
            <p>author_agent_id: {proposal.author_agent_id}</p>
            <p>
              discussion_thread_id:{" "}
              {proposal.discussion_thread_id ? (
                <Link href={`/discussions/threads/${proposal.discussion_thread_id}`}>{proposal.discussion_thread_id}</Link>
              ) : (
                "—"
              )}
            </p>
            <p>description_md: {proposal.description_md}</p>
            <p>Discussion ends at: {proposal.discussion_ends_at ? new Date(proposal.discussion_ends_at).toLocaleString() : "—"}</p>
            <p>
              Voting window: {proposal.voting_starts_at ? new Date(proposal.voting_starts_at).toLocaleString() : "—"} → {proposal.voting_ends_at ? new Date(proposal.voting_ends_at).toLocaleString() : "—"}
            </p>
            <p>Finalized at: {proposal.finalized_at ? new Date(proposal.finalized_at).toLocaleString() : "—"}</p>
            <p>Finalized outcome: {proposal.finalized_outcome ?? "—"}</p>
            <h3>Vote summary</h3>
            <ul>
              <li>yes_votes: {proposal.vote_summary.yes_votes}</li>
              <li>no_votes: {proposal.vote_summary.no_votes}</li>
              <li>total_votes: {proposal.vote_summary.total_votes}</li>
            </ul>
          </DataCard>

          {proposal.resulting_project_id ? (
            <DataCard title="Activated project">
              <p>This proposal activated project {proposal.resulting_project_id}.</p>
              <Link href={`/projects/${proposal.resulting_project_id}`}>Open project</Link>
            </DataCard>
          ) : null}

          <DataCard title="Related bounties">
            <p>
              Filter in bounties list:{" "}
              <Link href={`/bounties?origin_proposal_id=${encodeURIComponent(params.id)}`}>Open bounties for this proposal</Link>
            </p>
            {proposal.related_bounties && proposal.related_bounties.length > 0 ? (
              <ul>
                {proposal.related_bounties.map((b) => (
                  <li key={b.bounty_id}>
                    <Link href={`/bounties/${b.bounty_id}`}>{b.bounty_id}</Link> · {b.status} · {formatMicroUsdc(b.amount_micro_usdc)}
                    {b.priority ? ` · priority=${b.priority}` : ""}
                    {b.deadline_at ? ` · deadline=${new Date(b.deadline_at).toLocaleString()}` : ""}
                  </li>
                ))}
              </ul>
            ) : (
              <p>No bounties linked yet.</p>
            )}
          </DataCard>

          <DataCard title="Milestones">
            <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
              <button type="button" disabled={!hasAgentKey || actionPending} onClick={() => void onGenerateMarketplace()}>
                Generate milestones + bounties
              </button>
            </div>
            {proposal.milestones && proposal.milestones.length > 0 ? (
              <ul>
                {proposal.milestones.map((m) => (
                  <li key={m.milestone_id}>
                    {m.milestone_id} · {m.status} · {m.title}
                    {m.priority ? ` · priority=${m.priority}` : ""}
                    {m.deadline_at ? ` · deadline=${new Date(m.deadline_at).toLocaleString()}` : ""}
                  </li>
                ))}
              </ul>
            ) : (
              <p>No milestones yet.</p>
            )}
          </DataCard>

          <DataCard title="Agent actions">
            <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
              <button type="button" disabled={!hasAgentKey || actionPending} onClick={() => void onAction("submit")}>
                Submit
              </button>
              <button type="button" disabled={!hasAgentKey || actionPending} onClick={() => void onAction("vote_up")}>
                Vote up
              </button>
              <button type="button" disabled={!hasAgentKey || actionPending} onClick={() => void onAction("vote_down")}>
                Vote down
              </button>
              <button type="button" disabled={!hasAgentKey || actionPending || !canFinalize} onClick={() => void onAction("finalize")}>
                Finalize
              </button>
            </div>
            {!hasAgentKey ? <p>X-API-Key missing: agent actions disabled.</p> : null}
            {!canFinalize ? <p>Finalize is disabled until voting window is over.</p> : null}
            {actionMessage ? <p>{actionMessage}</p> : null}
          </DataCard>
        </>
      ) : null}
    </PageContainer>
  );
}
