"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";

import { DataCard, PageContainer } from "@/components/Cards";
import { EmptyState, Loading } from "@/components/State";
import { ErrorState } from "@/components/ErrorState";
import { api, readErrorMessage } from "@/lib/api";
import { formatDateTimeShort } from "@/lib/format";
import type { AlertsData, AlertItem, IndexerStatusData, StatsData } from "@/types";

function groupBySeverity(items: AlertItem[]): Record<string, AlertItem[]> {
  const out: Record<string, AlertItem[]> = {};
  for (const item of items) {
    const key = item.severity || "unknown";
    out[key] = out[key] ?? [];
    out[key].push(item);
  }
  return out;
}

function pickByPrefix(items: AlertItem[], prefix: string): AlertItem[] {
  return items.filter((item) => String(item.alert_type || "").startsWith(prefix));
}

export default function AutonomyPage() {
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [alerts, setAlerts] = useState<AlertsData | null>(null);
  const [indexerStatus, setIndexerStatus] = useState<IndexerStatusData | null>(null);
  const [stats, setStats] = useState<StatsData | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [alertsData, indexerData, statsData] = await Promise.all([
        api.getAlerts(),
        api.getIndexerStatus(),
        api.getStats(),
      ]);
      setAlerts(alertsData);
      setIndexerStatus(indexerData);
      setStats(statsData);
    } catch (err) {
      setError(readErrorMessage(err));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const items = useMemo(() => alerts?.items ?? [], [alerts]);
  const grouped = useMemo(() => groupBySeverity(items), [items]);
  const gitAlerts = useMemo(() => pickByPrefix(items, "git_outbox_"), [items]);
  const gitCriticalCount = useMemo(
    () => gitAlerts.filter((item) => item.severity === "critical").length,
    [gitAlerts],
  );
  const gitWarningCount = useMemo(
    () => gitAlerts.filter((item) => item.severity === "warning").length,
    [gitAlerts],
  );
  const gitPendingCount = useMemo(
    () =>
      gitAlerts.filter(
        (item) =>
          item.alert_type === "git_outbox_pending" ||
          item.alert_type === "git_outbox_pending_stale" ||
          item.alert_type === "git_outbox_processing" ||
          item.alert_type === "git_outbox_processing_stale",
      ).length,
    [gitAlerts],
  );
  const gitFailedCount = useMemo(
    () => gitAlerts.filter((item) => item.alert_type === "git_outbox_failed").length,
    [gitAlerts],
  );
  const gitHealth = useMemo(() => {
    if (gitCriticalCount > 0) {
      return "critical";
    }
    if (gitWarningCount > 0) {
      return "warning";
    }
    return "ok";
  }, [gitCriticalCount, gitWarningCount]);

  return (
    <PageContainer title="Autonomy Dashboard">
      {loading ? <Loading message="Loading alerts..." /> : null}
      {!loading && error ? <ErrorState message={error} onRetry={load} /> : null}
      {!loading && !error ? (
        <>
          {items.length === 0 ? <EmptyState message="No alerts. System looks clean." /> : null}
          <DataCard title="Quick links">
            <ul>
              <li>
                <Link href="/settlement">Settlement</Link>
              </li>
              <li>
                <Link href="/projects">Projects</Link>
              </li>
              <li>
                <Link href="/bounties">Bounties</Link>
              </li>
              <li>
                <Link href="/runbook">Runbook</Link>
              </li>
            </ul>
          </DataCard>

          <DataCard title="Git Automation Health">
            <p>status: {gitHealth}</p>
            <p>pending_or_processing: {gitPendingCount}</p>
            <p>failed: {gitFailedCount}</p>
            <p>warning: {gitWarningCount}</p>
            <p>critical: {gitCriticalCount}</p>
            {gitAlerts.length === 0 ? <p>No git_outbox alerts.</p> : null}
          </DataCard>

          {indexerStatus ? (
            <DataCard title="Indexer Runtime Health">
              <p>cursor_key: {indexerStatus.cursor_key}</p>
              <p>status: {indexerStatus.stale ? "stale" : indexerStatus.degraded ? "degraded" : "ok"}</p>
              <p>last_block: {indexerStatus.last_block_number ?? "n/a"}</p>
              <p>cursor_age_seconds: {indexerStatus.age_seconds ?? "n/a"} / {indexerStatus.max_age_seconds}</p>
              <p>
                scan_window_blocks: {indexerStatus.last_scan_window_blocks ?? "n/a"} / configured {indexerStatus.lookback_blocks_configured}
              </p>
              <p>min_scan_window_blocks: {indexerStatus.min_lookback_blocks_configured}</p>
              <p>degraded_age_seconds: {indexerStatus.degraded_age_seconds ?? 0} / {indexerStatus.degraded_max_age_seconds}</p>
              {indexerStatus.updated_at ? (
                <p>updated_at: {formatDateTimeShort(indexerStatus.updated_at)}</p>
              ) : null}
              {indexerStatus.degraded_since ? (
                <p>degraded_since: {formatDateTimeShort(indexerStatus.degraded_since)}</p>
              ) : null}
              {indexerStatus.last_error_hint ? (
                <p>last_error_hint: {indexerStatus.last_error_hint}</p>
              ) : null}
            </DataCard>
          ) : null}

          {stats ? (
            <DataCard title="Platform Capital Health">
              <p>
                reconciliation_status:{" "}
                {stats.platform_capital_reconciliation_ready == null
                  ? "missing"
                  : stats.platform_capital_reconciliation_ready
                    ? "ready"
                    : "not_ready"}
              </p>
              <p>
                ledger_micro_usdc:{" "}
                {stats.platform_capital_ledger_balance_micro_usdc ?? "n/a"}
              </p>
              <p>
                spendable_micro_usdc:{" "}
                {stats.platform_capital_spendable_balance_micro_usdc ?? "n/a"}
              </p>
              <p>
                delta_micro_usdc:{" "}
                {stats.platform_capital_reconciliation_delta_micro_usdc ?? "n/a"}
              </p>
              <p>
                max_age_seconds:{" "}
                {stats.platform_capital_reconciliation_max_age_seconds ?? "n/a"}
              </p>
              {stats.platform_capital_reconciliation_computed_at ? (
                <p>
                  reconciliation_computed_at:{" "}
                  {formatDateTimeShort(stats.platform_capital_reconciliation_computed_at)}
                </p>
              ) : null}
            </DataCard>
          ) : null}

          {items.length > 0
            ? Object.entries(grouped)
                .sort((a, b) => a[0].localeCompare(b[0]))
                .map(([severity, list]) => (
                  <DataCard key={severity} title={`severity=${severity} (${list.length})`}>
                    {list.map((a) => (
                      <div key={`${a.alert_type}:${a.ref ?? ""}:${a.observed_at}`} style={{ borderTop: "1px solid #eee", paddingTop: 8, marginTop: 8 }}>
                        <p>
                          <strong>{a.alert_type}</strong>
                          {a.ref ? <> ref={a.ref}</> : null}
                        </p>
                        <p>{a.message}</p>
                        {a.data ? (
                          <pre style={{ whiteSpace: "pre-wrap", wordBreak: "break-word" }}>
                            {JSON.stringify(a.data, null, 2)}
                          </pre>
                        ) : null}
                        <p style={{ opacity: 0.7 }}>observed_at: {formatDateTimeShort(a.observed_at)}</p>
                      </div>
                    ))}
                  </DataCard>
                ))
            : null}
        </>
      ) : null}
    </PageContainer>
  );
}
