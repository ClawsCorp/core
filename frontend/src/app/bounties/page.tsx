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
  const [originProposalIdFilter, setOriginProposalIdFilter] = useState("");
  const [originMilestoneIdFilter, setOriginMilestoneIdFilter] = useState("");
  const [statusFilter, setStatusFilter] = useState("");
  const [initialized, setInitialized] = useState(false);

  const fetchBounties = useCallback(
    async (filters: { projectId: string; status: string; originProposalId: string; originMilestoneId: string }) => {
    setLoading(true);
    setError(null);
    try {
      const result = await api.getBounties({
        projectId: filters.projectId.trim() ? filters.projectId.trim() : undefined,
        status: filters.status.trim() ? filters.status.trim() : undefined,
        originProposalId: filters.originProposalId.trim() ? filters.originProposalId.trim() : undefined,
        originMilestoneId: filters.originMilestoneId.trim() ? filters.originMilestoneId.trim() : undefined,
      });
      setItems(result.items);
    } catch (err) {
      setError(readErrorMessage(err));
    } finally {
      setLoading(false);
    }
    },
    [],
  );

  const syncFromUrl = useCallback(() => {
    if (typeof window === "undefined") {
      return { projectId: "", originProposalId: "", originMilestoneId: "", status: "" };
    }
    const params = new URLSearchParams(window.location.search);
    return {
      projectId: params.get("project_id") ?? "",
      originProposalId: params.get("origin_proposal_id") ?? "",
      originMilestoneId: params.get("origin_milestone_id") ?? "",
      status: params.get("status") ?? "",
    };
  }, []);

  useEffect(() => {
    // Read query params from the browser URL (avoid useSearchParams to keep the page statically exportable).
    const fromUrl = syncFromUrl();
    setProjectIdFilter(fromUrl.projectId);
    setOriginProposalIdFilter(fromUrl.originProposalId);
    setOriginMilestoneIdFilter(fromUrl.originMilestoneId);
    setStatusFilter(fromUrl.status);
    setInitialized(true);
    void fetchBounties(fromUrl);
  }, [fetchBounties, syncFromUrl]);

  useEffect(() => {
    if (!initialized) {
      return;
    }
    const onPopState = () => {
      const fromUrl = syncFromUrl();
      setProjectIdFilter(fromUrl.projectId);
      setOriginProposalIdFilter(fromUrl.originProposalId);
      setOriginMilestoneIdFilter(fromUrl.originMilestoneId);
      setStatusFilter(fromUrl.status);
      void fetchBounties(fromUrl);
    };
    window.addEventListener("popstate", onPopState);
    return () => window.removeEventListener("popstate", onPopState);
  }, [fetchBounties, initialized, syncFromUrl]);

  const applyFilters = (filters: { projectId: string; originProposalId: string; originMilestoneId: string; status: string }) => {
    setProjectIdFilter(filters.projectId);
    setOriginProposalIdFilter(filters.originProposalId);
    setOriginMilestoneIdFilter(filters.originMilestoneId);
    setStatusFilter(filters.status);
    const query = new URLSearchParams();
    if (filters.projectId.trim()) {
      query.set("project_id", filters.projectId.trim());
    }
    if (filters.originProposalId.trim()) {
      query.set("origin_proposal_id", filters.originProposalId.trim());
    }
    if (filters.originMilestoneId.trim()) {
      query.set("origin_milestone_id", filters.originMilestoneId.trim());
    }
    if (filters.status.trim()) {
      query.set("status", filters.status.trim());
    }
    const suffix = query.toString() ? `?${query.toString()}` : "";
    router.push(`/bounties${suffix}`);
    void fetchBounties(filters);
  };

  const onApplyFilters = () =>
    applyFilters({
      projectId: projectIdFilter,
      originProposalId: originProposalIdFilter,
      originMilestoneId: originMilestoneIdFilter,
      status: statusFilter,
    });
  const onReset = () => applyFilters({ projectId: "", originProposalId: "", originMilestoneId: "", status: "" });
  const onPreset = (status: string) =>
    applyFilters({
      projectId: projectIdFilter,
      originProposalId: originProposalIdFilter,
      originMilestoneId: originMilestoneIdFilter,
      status,
    });

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
            origin_proposal_id:{" "}
            <input
              value={originProposalIdFilter}
              onChange={(event) => setOriginProposalIdFilter(event.target.value)}
              placeholder="prp_..."
              style={{ padding: 6, minWidth: 220 }}
            />
          </label>
          <label>
            origin_milestone_id:{" "}
            <input
              value={originMilestoneIdFilter}
              onChange={(event) => setOriginMilestoneIdFilter(event.target.value)}
              placeholder="mil_..."
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
          <button type="button" onClick={onReset}>
            Reset
          </button>
          <button type="button" onClick={() => onPreset("submitted")}>
            Submitted
          </button>
          <button type="button" onClick={() => onPreset("eligible_for_payout")}>
            Ready to pay
          </button>
          <button type="button" onClick={() => onPreset("paid")}>
            Paid
          </button>
          <Link href="/runbook">Open runbook</Link>
        </div>
      </DataCard>

      {loading ? <Loading message="Loading bounties..." /> : null}
      {!loading && error ? <ErrorState message={error} onRetry={() => fetchBounties({ projectId: projectIdFilter, originProposalId: originProposalIdFilter, originMilestoneId: originMilestoneIdFilter, status: statusFilter })} /> : null}
      {!loading && !error && items.length === 0 ? <EmptyState message="No bounties found." /> : null}
      {!loading && !error && items.length > 0
        ? items.map((bounty) => (
            <DataCard key={bounty.bounty_id} title={bounty.title}>
              <p>bounty_id: {bounty.bounty_id}</p>
              <p>project_id: {bounty.project_id}</p>
              <p>origin_proposal_id: {bounty.origin_proposal_id ?? "—"}</p>
              <p>origin_milestone_id: {bounty.origin_milestone_id ?? "—"}</p>
              <p>status: {bounty.status}</p>
              <p>amount: {formatMicroUsdc(bounty.amount_micro_usdc)}</p>
              <p>priority: {bounty.priority ?? "—"}</p>
              <p>deadline_at: {bounty.deadline_at ? new Date(bounty.deadline_at).toLocaleString() : "—"}</p>
              <Link href={`/bounties/${bounty.bounty_id}`}>Open detail</Link>
            </DataCard>
          ))
        : null}
    </PageContainer>
  );
}
