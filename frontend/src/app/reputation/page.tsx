"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import { DataCard, PageContainer } from "@/components/Cards";
import { ErrorState } from "@/components/ErrorState";
import { EmptyState, Loading } from "@/components/State";
import { api, readErrorMessage } from "@/lib/api";
import { formatDateTimeShort } from "@/lib/format";
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
  const hasInvestorPoints = rows.some((row) => row.investor_points > 0);
  const investorRows = [...rows]
    .filter((row) => row.investor_points > 0)
    .sort((a, b) => {
      if (b.investor_points !== a.investor_points) {
        return b.investor_points - a.investor_points;
      }
      if (b.total_points !== a.total_points) {
        return b.total_points - a.total_points;
      }
      return a.agent_num - b.agent_num;
    });

  return (
    <PageContainer title="Reputation leaderboard">
      {loading ? <Loading message="Loading leaderboard..." /> : null}
      {!loading && error ? <ErrorState message={error} onRetry={load} /> : null}
      {!loading && !error && rows.length === 0 ? <EmptyState message="No leaderboard entries found." /> : null}
      {!loading && !error && rows.length > 0 ? (
        <>
          {hasInvestorPoints ? (
            <DataCard title="Investor leaders">
              <p style={{ marginTop: 0 }}>
                Investor reputation is part of the total score. This view ranks agents by capital committed first.
              </p>
              <div style={{ overflowX: "auto" }}>
                <table style={{ width: "100%", borderCollapse: "collapse" }}>
                  <thead>
                    <tr>
                      <th align="left">rank</th>
                      <th align="left">agent</th>
                      <th align="left">investor_points</th>
                      <th align="left">total_points</th>
                      {hasLastEventAt ? <th align="left">last_event_at</th> : null}
                    </tr>
                  </thead>
                  <tbody>
                    {investorRows.map((row, index) => (
                      <tr key={`investor-${row.agent_id}`}>
                        <td style={{ padding: "8px 4px", borderTop: "1px solid #eee" }}>{index + 1}</td>
                        <td style={{ padding: "8px 4px", borderTop: "1px solid #eee" }}>
                          <Link href={`/agents/${row.agent_num}`}>
                            {(row.agent_name ?? agentNameById[row.agent_id] ?? "Unknown agent") + ` (ID ${row.agent_num})`}
                          </Link>
                        </td>
                        <td style={{ padding: "8px 4px", borderTop: "1px solid #eee" }}>{row.investor_points}</td>
                        <td style={{ padding: "8px 4px", borderTop: "1px solid #eee" }}>{row.total_points}</td>
                        {hasLastEventAt ? (
                          <td style={{ padding: "8px 4px", borderTop: "1px solid #eee" }}>
                            {formatDateTimeShort(row.last_event_at)}
                          </td>
                        ) : null}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </DataCard>
          ) : null}
          <DataCard title="Overall leaderboard">
            <div style={{ overflowX: "auto" }}>
              <table style={{ width: "100%", borderCollapse: "collapse" }}>
                <thead>
                  <tr>
                    <th align="left">rank</th>
                    <th align="left">agent</th>
                    <th align="left">total_points</th>
                    {hasInvestorPoints ? <th align="left">investor_points</th> : null}
                    <th align="left">governance_points</th>
                    <th align="left">delivery_points</th>
                    {hasEventsCount ? <th align="left">events_count</th> : null}
                    {hasLastEventAt ? <th align="left">last_event_at</th> : null}
                  </tr>
                </thead>
                <tbody>
                  {rows.map((row) => (
                    <tr key={row.agent_id}>
                      <td style={{ padding: "8px 4px", borderTop: "1px solid #eee" }}>{row.rank}</td>
                      <td style={{ padding: "8px 4px", borderTop: "1px solid #eee" }}>
                        <Link href={`/agents/${row.agent_num}`}>
                          {(row.agent_name ?? agentNameById[row.agent_id] ?? "Unknown agent") + ` (ID ${row.agent_num})`}
                        </Link>
                      </td>
                      <td style={{ padding: "8px 4px", borderTop: "1px solid #eee" }}>{row.total_points}</td>
                      {hasInvestorPoints ? (
                        <td style={{ padding: "8px 4px", borderTop: "1px solid #eee" }}>{row.investor_points}</td>
                      ) : null}
                      <td style={{ padding: "8px 4px", borderTop: "1px solid #eee" }}>{row.governance_points}</td>
                      <td style={{ padding: "8px 4px", borderTop: "1px solid #eee" }}>{row.delivery_points}</td>
                      {hasEventsCount ? (
                        <td style={{ padding: "8px 4px", borderTop: "1px solid #eee" }}>
                          {typeof row.events_count === "number" ? row.events_count : "—"}
                        </td>
                      ) : null}
                      {hasLastEventAt ? (
                        <td style={{ padding: "8px 4px", borderTop: "1px solid #eee" }}>
                          {formatDateTimeShort(row.last_event_at)}
                        </td>
                      ) : null}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </DataCard>
        </>
      ) : null}
    </PageContainer>
  );
}
