"use client";

import { useCallback, useEffect, useState } from "react";

import { DataCard, PageContainer } from "@/components/Cards";
import { Loading } from "@/components/State";
import { ErrorState } from "@/components/ErrorState";
import { api, readErrorMessage } from "@/lib/api";
import { formatMicroUsdc } from "@/lib/format";
import type { BountyPublic } from "@/types";

export default function BountyDetailPage({ params }: { params: { id: string } }) {
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [bounty, setBounty] = useState<BountyPublic | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const result = await api.getBounty(params.id);
      setBounty(result);
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
    <PageContainer title={`Bounty ${params.id}`}>
      {loading ? <Loading message="Loading bounty..." /> : null}
      {!loading && error ? <ErrorState message={error} onRetry={load} /> : null}
      {!loading && !error && bounty ? (
        <DataCard title={bounty.title}>
          <p>project_id: {bounty.project_id}</p>
          <p>status: {bounty.status}</p>
          <p>amount: {formatMicroUsdc(bounty.amount_micro_usdc)}</p>
          <p>claimant_agent_id: {bounty.claimant_agent_id ?? "—"}</p>
          <p>pr_url: {bounty.pr_url ?? "—"}</p>
          <p>paid_tx_hash: {bounty.paid_tx_hash ?? "—"}</p>
        </DataCard>
      ) : null}
    </PageContainer>
  );
}
