"use client";

import { useCallback, useEffect, useState } from "react";

import { DataCard, PageContainer } from "@/components/Cards";
import { EmptyState, Loading } from "@/components/State";
import { ErrorState } from "@/components/ErrorState";
import { api, readErrorMessage } from "@/lib/api";
import { formatBoolean, formatMicroUsdc } from "@/lib/format";
import type { HealthResponse, SettlementMonthSummary, StatsData } from "@/types";

export default function HomePage() {
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [stats, setStats] = useState<StatsData | null>(null);
  const [latestMonth, setLatestMonth] = useState<SettlementMonthSummary | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [healthPayload, statsPayload, months] = await Promise.all([
        api.getHealth(),
        api.getStats(),
        api.getSettlementMonths(1, 0),
      ]);
      setHealth(healthPayload);
      setStats(statsPayload);
      setLatestMonth(months.items[0] ?? null);
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
    <PageContainer title="ClawsCorp Read-only Portal">
      {loading ? <Loading message="Loading dashboard..." /> : null}
      {!loading && error ? <ErrorState message={error} onRetry={load} /> : null}
      {!loading && !error ? (
        <>
          <DataCard title="Health">
            {health ? (
              <ul>
                <li>status: {health.status}</li>
                <li>version: {health.version}</li>
                <li>db: {health.db}</li>
                <li>timestamp: {health.timestamp}</li>
              </ul>
            ) : (
              <EmptyState message="health unavailable" />
            )}
          </DataCard>

          <DataCard title="Stats">
            {stats ? (
              <ul>
                <li>app_version: {stats.app_version}</li>
                <li>total_registered_agents: {stats.total_registered_agents}</li>
                <li>server_time_utc: {stats.server_time_utc}</li>
              </ul>
            ) : (
              <EmptyState message="stats unavailable" />
            )}
          </DataCard>

          <DataCard title="Latest settlement month">
            {latestMonth ? (
              <ul>
                <li>profit_month_id: {latestMonth.profit_month_id}</li>
                <li>revenue_sum: {formatMicroUsdc(latestMonth.revenue_sum_micro_usdc)}</li>
                <li>expense_sum: {formatMicroUsdc(latestMonth.expense_sum_micro_usdc)}</li>
                <li>profit_sum: {formatMicroUsdc(latestMonth.profit_sum_micro_usdc)}</li>
                <li>
                  distributor_balance: {formatMicroUsdc(latestMonth.distributor_balance_micro_usdc)}
                </li>
                <li>delta: {formatMicroUsdc(latestMonth.delta_micro_usdc)}</li>
                <li>ready: {formatBoolean(latestMonth.ready)}</li>
              </ul>
            ) : (
              <EmptyState message="No settlement months yet." />
            )}
          </DataCard>
        </>
      ) : null}
    </PageContainer>
  );
}
