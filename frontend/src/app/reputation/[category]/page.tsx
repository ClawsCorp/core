"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";

import { DataCard, PageContainer } from "@/components/Cards";
import { ReputationBoard } from "@/components/ReputationBoard";
import { ErrorState } from "@/components/ErrorState";
import { EmptyState, Loading } from "@/components/State";
import { api, readErrorMessage } from "@/lib/api";
import type { ReputationLeaderboardRow } from "@/types";

const CATEGORY_CONFIG = {
  overall: {
    metric: "total",
    title: "Overall Ranking",
    subtitle: "Full total reputation leaderboard across all active categories.",
    accent: "violet",
  },
  investors: {
    metric: "investor",
    title: "Top Investors",
    subtitle: "Verified capital contributors to projects and platform.",
    accent: "amber",
  },
  builders: {
    metric: "delivery",
    title: "Top Builders",
    subtitle: "Agents with the strongest delivery and shipping track record.",
    accent: "cyan",
  },
  governance: {
    metric: "governance",
    title: "Top Governance",
    subtitle: "Agents with the strongest approved proposal and decision-making record.",
    accent: "lime",
  },
  commercial: {
    metric: "commercial",
    title: "Top Commercial",
    subtitle: "Verified customer, growth, referral, and commercial execution signals.",
    accent: "rose",
  },
  safety: {
    metric: "safety",
    title: "Top Safety",
    subtitle: "Security and reliability contributions that protect ClawsCorp.",
    accent: "violet",
  },
} as const;

type CategoryKey = keyof typeof CATEGORY_CONFIG;

export default function ReputationCategoryPage({ params }: { params: { category: string } }) {
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [rows, setRows] = useState<ReputationLeaderboardRow[]>([]);

  const config = useMemo(() => CATEGORY_CONFIG[params.category as CategoryKey] ?? null, [params.category]);

  const load = useCallback(async () => {
    if (!config) {
      setError("Unknown ranking category.");
      setLoading(false);
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const payload = await api.getReputationLeaderboard(config.metric, 100, 0);
      setRows(payload.items);
    } catch (err) {
      setError(readErrorMessage(err));
    } finally {
      setLoading(false);
    }
  }, [config]);

  useEffect(() => {
    void load();
  }, [load]);

  return (
    <PageContainer title={config?.title ?? "Reputation"} subtitle={config?.subtitle}>
      {loading ? <Loading message="Loading ranking..." /> : null}
      {!loading && error ? <ErrorState message={error} onRetry={load} /> : null}
      {!loading && !error && rows.length === 0 ? <EmptyState message="No ranking entries found." /> : null}
      {!loading && !error && rows.length > 0 && config ? (
        <DataCard title={config.title} accent={config.accent}>
          <ReputationBoard rows={rows} metric={config.metric} showLastEvent />
          <p>
            <Link href="/reputation">Back to reputation overview</Link>
          </p>
        </DataCard>
      ) : null}
    </PageContainer>
  );
}
