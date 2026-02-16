"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";

import { DataCard, PageContainer } from "@/components/Cards";
import { EmptyState, Loading } from "@/components/State";
import { ErrorState } from "@/components/ErrorState";
import { api, readErrorMessage } from "@/lib/api";
import { formatDateTimeShort, formatMicroUsdc } from "@/lib/format";
import type { ProjectCapitalSummary } from "@/types";

export default function ProjectsCapitalPage() {
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [items, setItems] = useState<ProjectCapitalSummary[]>([]);
  const [projectIdFilter, setProjectIdFilter] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const result = await api.getProjectCapitalLeaderboard();
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

  const filtered = useMemo(() => {
    if (!projectIdFilter.trim()) {
      return items;
    }
    return items.filter((item) => item.project_id.includes(projectIdFilter.trim()));
  }, [items, projectIdFilter]);

  return (
    <PageContainer title="Project Capital">
      <DataCard title="Filters">
        <label>
          project_id:
          <input
            value={projectIdFilter}
            onChange={(event) => setProjectIdFilter(event.target.value)}
            placeholder="proj_..."
            style={{ marginLeft: 8, padding: 6 }}
          />
        </label>
      </DataCard>

      {loading ? <Loading message="Loading project capital leaderboard..." /> : null}
      {!loading && error ? <ErrorState message={error} onRetry={load} /> : null}
      {!loading && !error && filtered.length === 0 ? <EmptyState message="No capital data found." /> : null}
      {!loading && !error && filtered.length > 0
        ? filtered.map((item) => (
            <DataCard key={item.project_id} title={`${item.project_id} (ID ${item.project_num})`}>
              <p>balance_micro_usdc: {formatMicroUsdc(item.balance_micro_usdc)}</p>
              <p>events_count: {item.events_count}</p>
              <p>last_event_at: {formatDateTimeShort(item.last_event_at)}</p>
              <Link href={`/projects/${item.project_id}`}>Open project</Link>
            </DataCard>
          ))
        : null}
    </PageContainer>
  );
}
