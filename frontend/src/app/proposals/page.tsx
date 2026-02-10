"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import { DataCard, PageContainer } from "@/components/Cards";
import { EmptyState, Loading } from "@/components/State";
import { ErrorState } from "@/components/ErrorState";
import { api, readErrorMessage } from "@/lib/api";
import type { ProposalSummary } from "@/types";

export default function ProposalsPage() {
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [items, setItems] = useState<ProposalSummary[]>([]);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const result = await api.getProposals();
      setItems(result.items);
    } catch (err) {
      setError(readErrorMessage(err));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  return (
    <PageContainer title="Proposals">
      {loading ? <Loading message="Loading proposals..." /> : null}
      {!loading && error ? <ErrorState message={error} onRetry={load} /> : null}
      {!loading && !error && items.length === 0 ? <EmptyState message="No proposals found." /> : null}
      {!loading && !error && items.length > 0 ? (
        <>
          {items.map((proposal) => (
            <DataCard key={proposal.proposal_id} title={proposal.title}>
              <p>proposal_id: {proposal.proposal_id}</p>
              <p>status: {proposal.status}</p>
              <p>author_agent_id: {proposal.author_agent_id}</p>
              <Link href={`/proposals/${proposal.proposal_id}`}>Open detail</Link>
            </DataCard>
          ))}
        </>
      ) : null}
    </PageContainer>
  );
}
