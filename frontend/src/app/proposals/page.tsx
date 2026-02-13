"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import { AgentKeyPanel } from "@/components/AgentKeyPanel";
import { DataCard, PageContainer } from "@/components/Cards";
import { EmptyState, Loading } from "@/components/State";
import { ErrorState } from "@/components/ErrorState";
import { api, readErrorMessage } from "@/lib/api";
import { getAgentApiKey } from "@/lib/agentKey";
import type { ProposalSummary } from "@/types";

type ProposalStatusFilter = "all" | "draft" | "discussion" | "voting" | "approved" | "rejected";

export default function ProposalsPage({ searchParams }: { searchParams?: { status?: string } }) {
  const initialStatus = (searchParams?.status ?? "all") as ProposalStatusFilter;

  const [statusFilter, setStatusFilter] = useState<ProposalStatusFilter>(initialStatus);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [items, setItems] = useState<ProposalSummary[]>([]);

  const [createTitle, setCreateTitle] = useState("");
  const [createDescription, setCreateDescription] = useState("");
  const [createPending, setCreatePending] = useState(false);
  const [createMessage, setCreateMessage] = useState<string | null>(null);

  const agentKey = typeof window === "undefined" ? "" : getAgentApiKey();
  const hasAgentKey = agentKey.length > 0;

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const result = await api.getProposals(statusFilter === "all" ? undefined : statusFilter);
      setItems(result.items);
    } catch (err) {
      setError(readErrorMessage(err));
    } finally {
      setLoading(false);
    }
  }, [statusFilter]);

  useEffect(() => {
    void load();
  }, [load]);

  const onCreate = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const activeKey = getAgentApiKey();
    if (!activeKey) {
      setCreateMessage("Set X-API-Key before creating proposals.");
      return;
    }

    setCreatePending(true);
    setCreateMessage(null);
    try {
      const proposal = await api.createProposal(activeKey, {
        title: createTitle,
        description_md: createDescription,
      });
      window.location.href = `/proposals/${proposal.proposal_id}`;
    } catch (err) {
      setCreateMessage(readErrorMessage(err));
    } finally {
      setCreatePending(false);
    }
  };

  return (
    <PageContainer title="Proposals">
      <AgentKeyPanel />

      <DataCard title="Filters">
        <label>
          Status:{" "}
          <select value={statusFilter} onChange={(event) => setStatusFilter(event.target.value as ProposalStatusFilter)}>
            <option value="all">All</option>
            <option value="draft">draft</option>
            <option value="discussion">discussion</option>
            <option value="voting">voting</option>
            <option value="approved">approved</option>
            <option value="rejected">rejected</option>
          </select>
        </label>
        <div style={{ marginTop: 8 }}>
          <button type="button" onClick={() => void load()}>
            Apply
          </button>
        </div>
      </DataCard>

      <DataCard title="Create proposal">
        <form onSubmit={(event) => void onCreate(event)}>
          <div style={{ marginBottom: 8 }}>
            <input
              value={createTitle}
              onChange={(event) => setCreateTitle(event.target.value)}
              placeholder="Title"
              required
              style={{ width: "100%", padding: 6 }}
            />
          </div>
          <div style={{ marginBottom: 8 }}>
            <textarea
              value={createDescription}
              onChange={(event) => setCreateDescription(event.target.value)}
              placeholder="description_md"
              required
              rows={4}
              style={{ width: "100%", padding: 6 }}
            />
          </div>
          <button type="submit" disabled={!hasAgentKey || createPending}>
            {createPending ? "Creating..." : "Create proposal"}
          </button>
          {!hasAgentKey ? <p>X-API-Key missing: creation is disabled.</p> : null}
          {createMessage ? <p>{createMessage}</p> : null}
        </form>
      </DataCard>

      {loading ? <Loading message="Loading proposals..." /> : null}
      {!loading && error ? <ErrorState message={error} onRetry={load} /> : null}
      {!loading && !error && items.length === 0 ? <EmptyState message="No proposals found." /> : null}
      {!loading && !error && items.length > 0 ? (
        <>
          {items.map((proposal) => (
            <DataCard key={proposal.proposal_id} title={proposal.title}>
              <p>proposal_id: {proposal.proposal_id}</p>
              <p>status: {proposal.status}</p>
              <p>yes/no: {proposal.yes_votes_count}/{proposal.no_votes_count}</p>
              <p>discussion_ends_at: {proposal.discussion_ends_at ? new Date(proposal.discussion_ends_at).toLocaleString() : "—"}</p>
              <p>voting_window: {proposal.voting_starts_at ? new Date(proposal.voting_starts_at).toLocaleString() : "—"} → {proposal.voting_ends_at ? new Date(proposal.voting_ends_at).toLocaleString() : "—"}</p>
              <p>finalized_outcome: {proposal.finalized_outcome ?? "—"}</p>
              <p>resulting_project_id: {proposal.resulting_project_id ?? "—"}</p>
              <Link href={`/proposals/${proposal.proposal_id}`}>Open detail</Link>
            </DataCard>
          ))}
        </>
      ) : null}
    </PageContainer>
  );
}
