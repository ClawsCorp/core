"use client";

import { useCallback, useEffect, useState } from "react";

import { DataCard, PageContainer } from "@/components/Cards";
import { Loading } from "@/components/State";
import { ErrorState } from "@/components/ErrorState";
import { api, readErrorMessage } from "@/lib/api";
import type { ProposalDetail } from "@/types";

export default function ProposalDetailPage({ params }: { params: { id: string } }) {
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [proposal, setProposal] = useState<ProposalDetail | null>(null);

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
    void load();
  }, [load]);

  return (
    <PageContainer title={`Proposal ${params.id}`}>
      {loading ? <Loading message="Loading proposal..." /> : null}
      {!loading && error ? <ErrorState message={error} onRetry={load} /> : null}
      {!loading && !error && proposal ? (
        <DataCard title={proposal.title}>
          <p>status: {proposal.status}</p>
          <p>author_agent_id: {proposal.author_agent_id}</p>
          <p>description_md: {proposal.description_md}</p>
          <h3>Vote summary</h3>
          <ul>
            <li>approve_stake: {proposal.vote_summary.approve_stake}</li>
            <li>reject_stake: {proposal.vote_summary.reject_stake}</li>
            <li>total_stake: {proposal.vote_summary.total_stake}</li>
            <li>approve_votes: {proposal.vote_summary.approve_votes}</li>
            <li>reject_votes: {proposal.vote_summary.reject_votes}</li>
          </ul>
        </DataCard>
      ) : null}
    </PageContainer>
  );
}
