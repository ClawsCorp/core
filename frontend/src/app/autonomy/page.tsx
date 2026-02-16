"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";

import { DataCard, PageContainer } from "@/components/Cards";
import { EmptyState, Loading } from "@/components/State";
import { ErrorState } from "@/components/ErrorState";
import { api, readErrorMessage } from "@/lib/api";
import { formatDateTimeShort } from "@/lib/format";
import type { AlertsData, AlertItem } from "@/types";

function groupBySeverity(items: AlertItem[]): Record<string, AlertItem[]> {
  const out: Record<string, AlertItem[]> = {};
  for (const item of items) {
    const key = item.severity || "unknown";
    out[key] = out[key] ?? [];
    out[key].push(item);
  }
  return out;
}

export default function AutonomyPage() {
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [alerts, setAlerts] = useState<AlertsData | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await api.getAlerts();
      setAlerts(data);
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

  return (
    <PageContainer title="Autonomy Dashboard">
      {loading ? <Loading message="Loading alerts..." /> : null}
      {!loading && error ? <ErrorState message={error} onRetry={load} /> : null}
      {!loading && !error && items.length === 0 ? (
        <EmptyState message="No alerts. System looks clean." />
      ) : null}
      {!loading && !error && items.length > 0 ? (
        <>
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

          {Object.entries(grouped)
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
            ))}
        </>
      ) : null}
    </PageContainer>
  );
}
