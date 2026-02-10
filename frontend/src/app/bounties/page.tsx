"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import { DataCard, PageContainer } from "@/components/Cards";
import { EmptyState, Loading } from "@/components/State";
import { ErrorState } from "@/components/ErrorState";
import { api, readErrorMessage } from "@/lib/api";
import { formatMicroUsdc } from "@/lib/format";
import type { BountyPublic } from "@/types";

export default function BountiesPage() {
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [items, setItems] = useState<BountyPublic[]>([]);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const result = await api.getBounties();
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
    <PageContainer title="Bounties">
      {loading ? <Loading message="Loading bounties..." /> : null}
      {!loading && error ? <ErrorState message={error} onRetry={load} /> : null}
      {!loading && !error && items.length === 0 ? <EmptyState message="No bounties found." /> : null}
      {!loading && !error && items.length > 0
        ? items.map((bounty) => (
            <DataCard key={bounty.bounty_id} title={bounty.title}>
              <p>bounty_id: {bounty.bounty_id}</p>
              <p>project_id: {bounty.project_id}</p>
              <p>status: {bounty.status}</p>
              <p>amount: {formatMicroUsdc(bounty.amount_micro_usdc)}</p>
              <Link href={`/bounties/${bounty.bounty_id}`}>Open detail</Link>
            </DataCard>
          ))
        : null}
    </PageContainer>
  );
}
