"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";

import { DataCard, PageContainer } from "@/components/Cards";
import { ReputationBoard } from "@/components/ReputationBoard";
import { ErrorState } from "@/components/ErrorState";
import { EmptyState, Loading } from "@/components/State";
import { api, readErrorMessage } from "@/lib/api";
import type { ReputationLeaderboardRow } from "@/types";

const PAGE_SIZE = 100;

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
type BoardMetric = (typeof CATEGORY_CONFIG)[CategoryKey]["metric"];

function filterRowsForMetric(rows: ReputationLeaderboardRow[], metric: BoardMetric): ReputationLeaderboardRow[] {
  if (metric === "total") {
    return rows.filter((row) => row.total_points > 0);
  }
  if (metric === "investor") {
    return rows.filter((row) => row.investor_points > 0);
  }
  if (metric === "delivery") {
    return rows.filter((row) => row.delivery_points > 0);
  }
  if (metric === "governance") {
    return rows.filter((row) => row.governance_points > 0);
  }
  if (metric === "commercial") {
    return rows.filter((row) => row.commercial_points > 0);
  }
  return rows.filter((row) => row.safety_points > 0);
}

export default function ReputationCategoryPage({ params }: { params: { category: string } }) {
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [rows, setRows] = useState<ReputationLeaderboardRow[]>([]);
  const [offset, setOffset] = useState(0);

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
      const payload = await api.getReputationLeaderboard(config.metric, PAGE_SIZE, offset);
      setRows(filterRowsForMetric(payload.items, config.metric));
    } catch (err) {
      setError(readErrorMessage(err));
    } finally {
      setLoading(false);
    }
  }, [config, offset]);

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
          <p>
            {offset > 0 ? (
              <button type="button" onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}>
                Previous page
              </button>
            ) : null}
            {" "}
            {rows.length === PAGE_SIZE ? (
              <button type="button" onClick={() => setOffset(offset + PAGE_SIZE)}>
                Next page
              </button>
            ) : null}
          </p>
        </DataCard>
      ) : null}
    </PageContainer>
  );
}
