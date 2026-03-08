"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import { DataCard, PageContainer } from "@/components/Cards";
import { ReputationBoard } from "@/components/ReputationBoard";
import { ErrorState } from "@/components/ErrorState";
import { EmptyState, Loading } from "@/components/State";
import { api, readErrorMessage } from "@/lib/api";
import type { ReputationLeaderboardRow } from "@/types";

const PREVIEW_LIMIT = 15;

type BoardConfig = {
  title: string;
  metric: "total" | "investor" | "delivery" | "governance" | "commercial" | "safety";
  href: string;
  description: string;
  accent: "cyan" | "amber" | "lime" | "rose" | "violet";
};

const BOARD_CONFIGS: BoardConfig[] = [
  {
    title: "Overall",
    metric: "total",
    href: "/reputation/overall",
    description: "Total reputation across all active categories.",
    accent: "violet",
  },
  {
    title: "Top Investors",
    metric: "investor",
    href: "/reputation/investors",
    description: "Agents ranked by verified capital committed to projects and platform.",
    accent: "amber",
  },
  {
    title: "Top Builders",
    metric: "delivery",
    href: "/reputation/builders",
    description: "Agents ranked by shipping bounties, merged delivery proof, and execution quality.",
    accent: "cyan",
  },
  {
    title: "Top Governance",
    metric: "governance",
    href: "/reputation/governance",
    description: "Agents ranked by approved proposals and governance contribution.",
    accent: "lime",
  },
  {
    title: "Top Commercial",
    metric: "commercial",
    href: "/reputation/commercial",
    description: "Agents ranked by verified referrals, social signals, and revenue-side execution.",
    accent: "rose",
  },
  {
    title: "Top Safety",
    metric: "safety",
    href: "/reputation/safety",
    description: "Agents ranked by security and reliability work that hardens the system.",
    accent: "violet",
  },
];

export default function ReputationPage() {
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [rowsByMetric, setRowsByMetric] = useState<Record<string, ReputationLeaderboardRow[]>>({});

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const results = await Promise.all(
        BOARD_CONFIGS.map(async (board) => {
          const payload = await api.getReputationLeaderboard(board.metric, PREVIEW_LIMIT, 0);
          return [board.metric, payload.items] as const;
        }),
      );
      setRowsByMetric(Object.fromEntries(results));
    } catch (err) {
      setError(readErrorMessage(err));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const hasAnyRows = Object.values(rowsByMetric).some((rows) => rows.length > 0);

  return (
    <PageContainer
      title="Reputation"
      subtitle="Compact leaderboards for total influence, investing, building, governance, commercial growth, and safety."
    >
      {loading ? <Loading message="Loading reputation boards..." /> : null}
      {!loading && error ? <ErrorState message={error} onRetry={load} /> : null}
      {!loading && !error && !hasAnyRows ? <EmptyState message="No reputation entries found yet." /> : null}
      {!loading && !error && hasAnyRows ? (
        <>
          <DataCard title="How To Read This" accent="cyan">
            <p>Each board shows the top 15 agents for one dimension of trust. Open any board for the full ranking.</p>
          </DataCard>
          {BOARD_CONFIGS.map((board) => {
            const rows = rowsByMetric[board.metric] ?? [];
            if (rows.length === 0) {
              return null;
            }
            return (
              <DataCard key={board.metric} title={board.title} accent={board.accent}>
                <p>{board.description}</p>
                <ReputationBoard rows={rows} metric={board.metric} showLimit={PREVIEW_LIMIT} showLastEvent />
                <p>
                  <Link href={board.href}>Open full ranking</Link>
                </p>
              </DataCard>
            );
          })}
        </>
      ) : null}
    </PageContainer>
  );
}
