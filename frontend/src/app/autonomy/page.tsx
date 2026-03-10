"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";

import { DataCard, PageContainer } from "@/components/Cards";
import { EmptyState, Loading } from "@/components/State";
import { ErrorState } from "@/components/ErrorState";
import { api, readErrorMessage } from "@/lib/api";
import { formatDateTimeShort, formatMicroUsdc } from "@/lib/format";
import type { AlertsData, AlertItem, IndexerStatusData, PlatformFundingSummary, SocialVerifierDecisionPublic, StatsData } from "@/types";

import styles from "./page.module.css";

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

type Tone = "ok" | "warning" | "critical" | "neutral";

function toneFromSeverity(severity: string): Tone {
  if (severity === "ok" || severity === "healthy") {
    return "ok";
  }
  if (severity === "degraded" || severity === "critical") {
    return "critical";
  }
  if (severity === "stale" || severity === "warning") {
    return "warning";
  }
  if (severity === "critical") {
    return "critical";
  }
  if (severity === "warning") {
    return "warning";
  }
  if (severity === "info") {
    return "neutral";
  }
  return "neutral";
}

function pill(label: string, tone: Tone) {
  return <span className={`${styles.pill} ${styles[`pill_${tone}`]}`}>{label}</span>;
}

export default function AutonomyPage() {
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [alerts, setAlerts] = useState<AlertsData | null>(null);
  const [indexerStatus, setIndexerStatus] = useState<IndexerStatusData | null>(null);
  const [stats, setStats] = useState<StatsData | null>(null);
  const [platformFunding, setPlatformFunding] = useState<PlatformFundingSummary | null>(null);
  const [socialVerifierDecisions, setSocialVerifierDecisions] = useState<SocialVerifierDecisionPublic[]>([]);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [alertsData, indexerData, statsData, platformFundingData] = await Promise.all([
        api.getAlerts(),
        api.getIndexerStatus(),
        api.getStats(),
        api.getPlatformFundingSummary(),
      ]);
      const socialDecisionsData = await api.getSocialVerifierDecisions({ limit: 10, offset: 0 }).catch(() => null);
      setAlerts(alertsData);
      setIndexerStatus(indexerData);
      setStats(statsData);
      setPlatformFunding(platformFundingData);
      setSocialVerifierDecisions(socialDecisionsData?.items ?? []);
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

  const indexerHealthLabel = !indexerStatus
    ? "unknown"
    : indexerStatus.degraded
      ? "degraded"
      : indexerStatus.stale
        ? "stale"
        : "healthy";

  return (
    <PageContainer
      title="Autonomy Dashboard"
      subtitle="Runtime signals for agent-driven execution, reconciliation gates, and autonomous delivery flow."
    >
      {loading ? <Loading message="Loading alerts..." /> : null}
      {!loading && error ? <ErrorState message={error} onRetry={load} /> : null}
      {!loading && !error ? (
        <>
          <DataCard title="Autonomy Snapshot" accent="violet">
            <div className={styles.metricGrid}>
              <div className={styles.metricItem}>
                <span>Git health</span>
                <strong>{gitHealth}</strong>
                {pill(gitHealth, toneFromSeverity(gitHealth))}
              </div>
              <div className={styles.metricItem}>
                <span>Indexer health</span>
                <strong>{indexerHealthLabel}</strong>
                {pill(indexerHealthLabel, toneFromSeverity(indexerHealthLabel))}
              </div>
              <div className={styles.metricItem}>
                <span>Critical alerts</span>
                <strong>{grouped["critical"]?.length ?? 0}</strong>
                {pill("critical", "critical")}
              </div>
              <div className={styles.metricItem}>
                <span>Warnings</span>
                <strong>{grouped["warning"]?.length ?? 0}</strong>
                {pill("warning", "warning")}
              </div>
            </div>
          </DataCard>

          <DataCard title="Quick links" accent="cyan">
            <div className={styles.linkCloud}>
              <Link href="/settlement">Settlement</Link>
              <Link href="/projects">Projects</Link>
              <Link href="/bounties">Bounties</Link>
              <Link href="/runbook">Runbook</Link>
              <Link href="/discussions">Discussions</Link>
            </div>
          </DataCard>

          {items.length === 0 ? <EmptyState message="No alerts. System looks clean." /> : null}

          <DataCard title="Telegram / Social Verifier" accent="cyan">
            {socialVerifierDecisions.length === 0 ? (
              <p>No recent social verifier decisions yet.</p>
            ) : (
              <div className={styles.kvList}>
                {socialVerifierDecisions.map((item) => (
                  <div key={item.decision_id} className={styles.kvRow}>
                    <span>
                      {item.decision_status}
                      {item.reason_code ? ` / ${item.reason_code}` : ""}
                      {item.account_handle ? ` / @${item.account_handle}` : ""}
                    </span>
                    <strong>{formatDateTimeShort(item.decided_at)}</strong>
                  </div>
                ))}
              </div>
            )}
          </DataCard>

          <DataCard title="Git Automation Health" accent="rose">
            <div className={styles.kvList}>
              <div className={styles.kvRow}>
                <span>Status</span>
                <strong>
                  {gitHealth} {pill(gitHealth, toneFromSeverity(gitHealth))}
                </strong>
              </div>
              <div className={styles.kvRow}>
                <span>Pending or processing</span>
                <strong>{gitPendingCount}</strong>
              </div>
              <div className={styles.kvRow}>
                <span>Failed</span>
                <strong>{gitFailedCount}</strong>
              </div>
              <div className={styles.kvRow}>
                <span>Warnings</span>
                <strong>{gitWarningCount}</strong>
              </div>
              <div className={styles.kvRow}>
                <span>Critical</span>
                <strong>{gitCriticalCount}</strong>
              </div>
            </div>
            {gitAlerts.length === 0 ? <p>No git outbox alerts right now.</p> : null}
          </DataCard>

          {indexerStatus ? (
            <DataCard title="Indexer Runtime Health" accent="amber">
              <div className={styles.kvList}>
                <div className={styles.kvRow}>
                  <span>Cursor key</span>
                  <strong>{indexerStatus.cursor_key}</strong>
                </div>
                <div className={styles.kvRow}>
                  <span>Status</span>
                  <strong>
                    {indexerHealthLabel} {pill(indexerHealthLabel, toneFromSeverity(indexerHealthLabel))}
                  </strong>
                </div>
                <div className={styles.kvRow}>
                  <span>Last indexed block</span>
                  <strong>{indexerStatus.last_block_number ?? "n/a"}</strong>
                </div>
                <div className={styles.kvRow}>
                  <span>Cursor age vs max</span>
                  <strong>
                    {indexerStatus.age_seconds ?? "n/a"} / {indexerStatus.max_age_seconds}s
                  </strong>
                </div>
                <div className={styles.kvRow}>
                  <span>Scan window (actual / configured)</span>
                  <strong>
                    {indexerStatus.last_scan_window_blocks ?? "n/a"} / {indexerStatus.lookback_blocks_configured}
                  </strong>
                </div>
                <div className={styles.kvRow}>
                  <span>Minimum scan window</span>
                  <strong>{indexerStatus.min_lookback_blocks_configured}</strong>
                </div>
                <div className={styles.kvRow}>
                  <span>Degraded age vs max</span>
                  <strong>
                    {indexerStatus.degraded_age_seconds ?? 0} / {indexerStatus.degraded_max_age_seconds}s
                  </strong>
                </div>
                {indexerStatus.updated_at ? (
                  <div className={styles.kvRow}>
                    <span>Updated at</span>
                    <strong>{formatDateTimeShort(indexerStatus.updated_at)}</strong>
                  </div>
                ) : null}
                {indexerStatus.degraded_since ? (
                  <div className={styles.kvRow}>
                    <span>Degraded since</span>
                    <strong>{formatDateTimeShort(indexerStatus.degraded_since)}</strong>
                  </div>
                ) : null}
              </div>
              {indexerStatus.last_error_hint ? (
                <p>
                  Last error hint: <code>{indexerStatus.last_error_hint}</code>
                </p>
              ) : null}
            </DataCard>
          ) : null}

          {stats ? (
            <DataCard title="Platform Capital Health" accent="lime">
              <div className={styles.kvList}>
                <div className={styles.kvRow}>
                  <span>Reconciliation status</span>
                  <strong>
                    {stats.platform_capital_reconciliation_ready == null
                      ? "missing"
                      : stats.platform_capital_reconciliation_ready
                        ? "ready"
                        : "not_ready"}
                  </strong>
                </div>
                <div className={styles.kvRow}>
                  <span>Ledger balance</span>
                  <strong>{formatMicroUsdc(stats.platform_capital_ledger_balance_micro_usdc)}</strong>
                </div>
                <div className={styles.kvRow}>
                  <span>Spendable balance</span>
                  <strong>{formatMicroUsdc(stats.platform_capital_spendable_balance_micro_usdc)}</strong>
                </div>
                <div className={styles.kvRow}>
                  <span>Reconciliation delta</span>
                  <strong>{formatMicroUsdc(stats.platform_capital_reconciliation_delta_micro_usdc)}</strong>
                </div>
                <div className={styles.kvRow}>
                  <span>Max reconciliation age</span>
                  <strong>{stats.platform_capital_reconciliation_max_age_seconds ?? "n/a"}s</strong>
                </div>
              </div>
              {stats.platform_capital_reconciliation_computed_at ? (
                <p>Computed at: {formatDateTimeShort(stats.platform_capital_reconciliation_computed_at)}</p>
              ) : null}
            </DataCard>
          ) : null}

          {platformFunding ? (
            <DataCard title="Platform Funding Progress" accent="cyan">
              <div className={styles.kvList}>
                <div className={styles.kvRow}>
                  <span>Funding pool</span>
                  <strong>{platformFunding.funding_pool_address ?? "not configured"}</strong>
                </div>
                <div className={styles.kvRow}>
                  <span>Open round</span>
                  <strong>
                    {platformFunding.open_round
                      ? `${platformFunding.open_round.round_id}${platformFunding.open_round.title ? ` (${platformFunding.open_round.title})` : ""}`
                      : "—"}
                  </strong>
                </div>
                <div className={styles.kvRow}>
                  <span>Open round raised</span>
                  <strong>
                    {formatMicroUsdc(platformFunding.open_round_raised_micro_usdc)}
                    {platformFunding.open_round?.cap_micro_usdc
                      ? ` / ${formatMicroUsdc(platformFunding.open_round.cap_micro_usdc)}`
                      : ""}
                  </strong>
                </div>
                <div className={styles.kvRow}>
                  <span>Total raised</span>
                  <strong>{formatMicroUsdc(platformFunding.total_raised_micro_usdc)}</strong>
                </div>
                <div className={styles.kvRow}>
                  <span>Contributors</span>
                  <strong>{platformFunding.contributors_total_count}</strong>
                </div>
                <div className={styles.kvRow}>
                  <span>Data source</span>
                  <strong>{platformFunding.contributors_data_source}</strong>
                </div>
                <div className={styles.kvRow}>
                  <span>Unattributed</span>
                  <strong>{formatMicroUsdc(platformFunding.unattributed_micro_usdc)}</strong>
                </div>
                <div className={styles.kvRow}>
                  <span>Last deposit at</span>
                  <strong>{formatDateTimeShort(platformFunding.last_deposit_at)}</strong>
                </div>
              </div>
              {platformFunding.blocked_reason ? <p>Blocked reason: {platformFunding.blocked_reason}</p> : null}
              {platformFunding.contributors.length > 0 ? (
                <>
                  <p>Cap table (top {platformFunding.contributors.length})</p>
                  <ul>
                    {platformFunding.contributors.map((row) => (
                      <li key={row.address}>
                        {row.address}: {formatMicroUsdc(row.amount_micro_usdc)}
                      </li>
                    ))}
                  </ul>
                </>
              ) : null}
            </DataCard>
          ) : null}

          {items.length > 0
            ? Object.entries(grouped)
                .sort((a, b) => a[0].localeCompare(b[0]))
                .map(([severity, list]) => (
                  <DataCard
                    key={severity}
                    title={`Alerts: ${severity} (${list.length})`}
                    accent={severity === "critical" ? "rose" : severity === "warning" ? "amber" : "violet"}
                  >
                    {list.map((a) => (
                      <div key={`${a.alert_type}:${a.ref ?? ""}:${a.observed_at}`} className={styles.alertItem}>
                        <p>
                          <strong>{a.alert_type}</strong>
                          {a.ref ? <> ref={a.ref}</> : null} {pill(a.severity || "unknown", toneFromSeverity(a.severity || "unknown"))}
                        </p>
                        <p>{a.message}</p>
                        {a.data ? (
                          <pre className={styles.alertData}>
                            {JSON.stringify(a.data, null, 2)}
                          </pre>
                        ) : null}
                        <p>Observed at: {formatDateTimeShort(a.observed_at)}</p>
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
