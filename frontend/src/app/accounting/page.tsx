"use client";

import { useCallback, useEffect, useState } from "react";

import { DataCard, PageContainer } from "@/components/Cards";
import { EmptyState, Loading } from "@/components/State";
import { ErrorState } from "@/components/ErrorState";
import { api, readErrorMessage } from "@/lib/api";
import { formatMicroUsdc } from "@/lib/format";
import type { AccountingMonthSummary } from "@/types";

export default function AccountingPage() {
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [items, setItems] = useState<AccountingMonthSummary[]>([]);

  const [projectId, setProjectId] = useState("");
  const [profitMonthId, setProfitMonthId] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const result = await api.getAccountingMonths({
        projectId: projectId.trim() ? projectId.trim() : undefined,
        profitMonthId: profitMonthId.trim() ? profitMonthId.trim() : undefined,
        limit: 24,
        offset: 0,
      });
      setItems(result.items);
    } catch (err) {
      setError(readErrorMessage(err));
    } finally {
      setLoading(false);
    }
  }, [projectId, profitMonthId]);

  useEffect(() => {
    void load();
  }, [load]);

  return (
    <PageContainer title="Accounting">
      <DataCard title="Filters">
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
          <label>
            project_id:{" "}
            <input
              value={projectId}
              onChange={(e) => setProjectId(e.target.value)}
              placeholder="prj_..."
              style={{ padding: 6, minWidth: 220 }}
            />
          </label>
          <label>
            profit_month_id:{" "}
            <input
              value={profitMonthId}
              onChange={(e) => setProfitMonthId(e.target.value)}
              placeholder="YYYYMM"
              style={{ padding: 6, minWidth: 140 }}
            />
          </label>
          <button type="button" onClick={() => void load()}>
            Apply
          </button>
        </div>
      </DataCard>

      {loading ? <Loading message="Loading accounting..." /> : null}
      {!loading && error ? <ErrorState message={error} onRetry={load} /> : null}
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

