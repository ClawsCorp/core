"use client";

import { useCallback, useEffect, useState } from "react";

import { DataCard, PageContainer } from "@/components/Cards";
import { EmptyState, Loading } from "@/components/State";
import { ErrorState } from "@/components/ErrorState";
import { api, readErrorMessage } from "@/lib/api";
import { formatMicroUsdc } from "@/lib/format";
import type { AccountingMonthSummary } from "@/types";

function parseFiltersFromSearch(search: string): { projectId: string; profitMonthId: string } {
  const params = new URLSearchParams(search.startsWith("?") ? search.slice(1) : search);
  return {
    projectId: params.get("project_id") ?? "",
    profitMonthId: params.get("profit_month_id") ?? "",
  };
}

function buildSearchFromFilters(filters: { projectId: string; profitMonthId: string }): string {
  const params = new URLSearchParams();
  if (filters.projectId.trim()) {
    params.set("project_id", filters.projectId.trim());
  }
  if (filters.profitMonthId.trim()) {
    params.set("profit_month_id", filters.profitMonthId.trim());
  }
  const query = params.toString();
  return query ? `?${query}` : "";
}

export default function AccountingPage() {
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [items, setItems] = useState<AccountingMonthSummary[]>([]);

  const initialFilters =
    typeof window === "undefined"
      ? { projectId: "", profitMonthId: "" }
      : parseFiltersFromSearch(window.location.search);

  const [draftProjectId, setDraftProjectId] = useState(initialFilters.projectId);
  const [draftProfitMonthId, setDraftProfitMonthId] = useState(initialFilters.profitMonthId);
  const [appliedFilters, setAppliedFilters] = useState(initialFilters);

  const load = useCallback(async (filters: { projectId: string; profitMonthId: string }) => {
    setLoading(true);
    setError(null);
    try {
      const result = await api.getAccountingMonths({
        projectId: filters.projectId.trim() ? filters.projectId.trim() : undefined,
        profitMonthId: filters.profitMonthId.trim() ? filters.profitMonthId.trim() : undefined,
        limit: 24,
        offset: 0,
      });
      setItems(result.items);
    } catch (err) {
      setError(readErrorMessage(err));
    } finally {
      setLoading(false);
    }
  }, []);

  const syncFromUrl = useCallback(() => {
    if (typeof window === "undefined") {
      return;
    }
    const parsed = parseFiltersFromSearch(window.location.search);
    setDraftProjectId(parsed.projectId);
    setDraftProfitMonthId(parsed.profitMonthId);
    setAppliedFilters(parsed);
    void load(parsed);
  }, [load]);

  useEffect(() => {
    syncFromUrl();
    if (typeof window === "undefined") {
      return;
    }
    const onPop = () => syncFromUrl();
    window.addEventListener("popstate", onPop);
    return () => window.removeEventListener("popstate", onPop);
  }, [syncFromUrl]);

  const apply = () => {
    const next = { projectId: draftProjectId, profitMonthId: draftProfitMonthId };
    setAppliedFilters(next);
    if (typeof window !== "undefined") {
      const search = buildSearchFromFilters(next);
      const url = `${window.location.pathname}${search}`;
      window.history.pushState({}, "", url);
    }
    void load(next);
  };

  const reset = () => {
    setDraftProjectId("");
    setDraftProfitMonthId("");
    const next = { projectId: "", profitMonthId: "" };
    setAppliedFilters(next);
    if (typeof window !== "undefined") {
      window.history.pushState({}, "", window.location.pathname);
    }
    void load(next);
  };

  return (
    <PageContainer title="Accounting">
      <DataCard title="Filters">
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
          <label>
            project_id:{" "}
            <input
              value={draftProjectId}
              onChange={(e) => setDraftProjectId(e.target.value)}
              placeholder="prj_..."
              style={{ padding: 6, minWidth: 220 }}
            />
          </label>
          <label>
            profit_month_id:{" "}
            <input
              value={draftProfitMonthId}
              onChange={(e) => setDraftProfitMonthId(e.target.value)}
              placeholder="YYYYMM"
              style={{ padding: 6, minWidth: 140 }}
            />
          </label>
          <button type="button" onClick={apply}>
            Apply
          </button>
          <button type="button" onClick={reset}>
            Reset
          </button>
        </div>
        {appliedFilters.projectId.trim() || appliedFilters.profitMonthId.trim() ? (
          <p style={{ marginTop: 8 }}>
            Applied: project_id={appliedFilters.projectId.trim() || "—"} profit_month_id={appliedFilters.profitMonthId.trim() || "—"}
          </p>
        ) : null}
      </DataCard>

      {loading ? <Loading message="Loading accounting..." /> : null}
      {!loading && error ? <ErrorState message={error} onRetry={() => load(appliedFilters)} /> : null}
      {!loading && !error && items.length === 0 ? <EmptyState message="No accounting months found." /> : null}
      {!loading && !error && items.length > 0 ? (
        <DataCard title="Months">
          <ul>
            {items.map((m) => (
              <li key={m.profit_month_id}>
                {m.profit_month_id}: revenue={formatMicroUsdc(m.revenue_sum_micro_usdc)} expense={formatMicroUsdc(m.expense_sum_micro_usdc)} profit={formatMicroUsdc(m.profit_sum_micro_usdc)}
              </li>
            ))}
          </ul>
        </DataCard>
      ) : null}
    </PageContainer>
  );
}
