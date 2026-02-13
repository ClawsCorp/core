"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import { DataCard, PageContainer } from "@/components/Cards";
import { EmptyState, Loading } from "@/components/State";
import { ErrorState } from "@/components/ErrorState";
import { api, readErrorMessage } from "@/lib/api";
import { formatMicroUsdc } from "@/lib/format";
import type { BountyPublic } from "@/types";

export default function BountiesPage() {
  const router = useRouter();

  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [items, setItems] = useState<BountyPublic[]>([]);
  const [projectIdFilter, setProjectIdFilter] = useState("");
  const [statusFilter, setStatusFilter] = useState("");
  const [initialized, setInitialized] = useState(false);

  useEffect(() => {
    // Read query params from the browser URL (avoid useSearchParams to keep the page statically exportable).
    if (typeof window === "undefined") {
      return;
    }
    const params = new URLSearchParams(window.location.search);
    setProjectIdFilter(params.get("project_id") ?? "");
    setStatusFilter(params.get("status") ?? "");
    setInitialized(true);
  }, []);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const result = await api.getBounties({
        projectId: projectIdFilter.trim() ? projectIdFilter.trim() : undefined,
        status: statusFilter.trim() ? statusFilter.trim() : undefined,
      });
      setItems(result.items);
    } catch (err) {
      setError(readErrorMessage(err));
    } finally {
      setLoading(false);
    }
  }, [projectIdFilter, statusFilter]);

  useEffect(() => {
    if (!initialized) {
      return;
    }
    void load();
  }, [initialized, load]);

  const onApplyFilters = () => {
    const query = new URLSearchParams();
    if (projectIdFilter.trim()) {
      query.set("project_id", projectIdFilter.trim());
    }
    if (statusFilter.trim()) {
      query.set("status", statusFilter.trim());
    }
    const suffix = query.toString() ? `?${query.toString()}` : "";
    router.push(`/bounties${suffix}`);
    void load();
  };

  return (
    <PageContainer title="Bounties">
      <DataCard title="Filters">
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
          <label>
            project_id:{" "}
            <input
              value={projectIdFilter}
              onChange={(event) => setProjectIdFilter(event.target.value)}
              placeholder="prj_..."
              style={{ padding: 6, minWidth: 220 }}
            />
          </label>
          <label>
            status:{" "}
            <select value={statusFilter} onChange={(event) => setStatusFilter(event.target.value)} style={{ padding: 6 }}>
              <option value="">(all)</option>
              <option value="open">open</option>
              <option value="claimed">claimed</option>
              <option value="submitted">submitted</option>
              <option value="eligible_for_payout">eligible_for_payout</option>
              <option value="paid">paid</option>
            </select>
          </label>
          <button type="button" onClick={onApplyFilters}>
            Apply
          </button>
          <Link href="/runbook">Open runbook</Link>
        </div>
      </DataCard>

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
