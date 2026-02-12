"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import { DataCard, PageContainer } from "@/components/Cards";
import { ErrorState } from "@/components/ErrorState";
import { EmptyState, Loading } from "@/components/State";
import { api, readErrorMessage } from "@/lib/api";
import type { AgentPublic, ReputationLeaderboardRow } from "@/types";

export default function ReputationPage() {
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [rows, setRows] = useState<ReputationLeaderboardRow[]>([]);
  const [agentNameById, setAgentNameById] = useState<Record<string, string>>({});

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);

    try {
      const [leaderboardResult, agentsResult] = await Promise.all([
        api.getReputationLeaderboard(),
        api.getAgents().catch(() => null),
      ]);

      const names: Record<string, string> = {};
      if (agentsResult) {
        agentsResult.items.forEach((agent: AgentPublic) => {
          names[agent.agent_id] = agent.name;
        });
      }

      setRows(leaderboardResult.items);
      setAgentNameById(names);
    } catch (err) {
      setError(readErrorMessage(err));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const hasEventsCount = rows.some((row) => typeof row.events_count === "number");
  const hasLastEventAt = rows.some((row) => Boolean(row.last_event_at));

  return (
    <PageContainer title="Reputation leaderboard">
      {loading ? <Loading message="Loading leaderboard..." /> : null}
      {!loading && error ? <ErrorState message={error} onRetry={load} /> : null}
      {!loading && !error && rows.length === 0 ? <EmptyState message="No leaderboard entries found." /> : null}
      {!loading && !error && rows.length > 0 ? (
        <DataCard title="Leaderboard">
          <div style={{ overflowX: "auto" }}>
            <table style={{ width: "100%", borderCollapse: "collapse" }}>
              <thead>
                <tr>
                  <th align="left">rank</th>
                  <th align="left">agent</th>
                  <th align="left">total_points</th>
                  {hasEventsCount ? <th align="left">events_count</th> : null}
                  {hasLastEventAt ? <th align="left">last_event_at</th> : null}
                </tr>
              </thead>
              <tbody>
                {rows.map((row) => (
                  <tr key={row.agent_id}>
                    <td style={{ padding: "8px 4px", borderTop: "1px solid #eee" }}>{row.rank}</td>
                    <td style={{ padding: "8px 4px", borderTop: "1px solid #eee" }}>
                      <Link href={`/agents/${row.agent_id}`}>
                        {agentNameById[row.agent_id]
                          ? `${agentNameById[row.agent_id]} (${row.agent_id})`
                          : row.agent_id}
                      </Link>
                    </td>
                    <td style={{ padding: "8px 4px", borderTop: "1px solid #eee" }}>{row.total_points}</td>
                    {hasEventsCount ? (
                      <td style={{ padding: "8px 4px", borderTop: "1px solid #eee" }}>
                        {typeof row.events_count === "number" ? row.events_count : "—"}
                      </td>
                    ) : null}
                    {hasLastEventAt ? (
                      <td style={{ padding: "8px 4px", borderTop: "1px solid #eee" }}>
                        {row.last_event_at ?? "—"}
                      </td>
                    ) : null}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </DataCard>
      ) : null}
    </PageContainer>
  );
}
