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
  const [investorRows, setInvestorRows] = useState<ReputationLeaderboardRow[]>([]);
  const [commercialRows, setCommercialRows] = useState<ReputationLeaderboardRow[]>([]);
  const [safetyRows, setSafetyRows] = useState<ReputationLeaderboardRow[]>([]);
  const [agentNameById, setAgentNameById] = useState<Record<string, string>>({});

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);

    try {
      const [leaderboardResult, investorResult, commercialResult, safetyResult, agentsResult] = await Promise.all([
        api.getReputationLeaderboard(),
        api.getReputationLeaderboard("investor").catch(() => null),
        api.getReputationLeaderboard("commercial").catch(() => null),
        api.getReputationLeaderboard("safety").catch(() => null),
        api.getAgents().catch(() => null),
      ]);

      const names: Record<string, string> = {};
      if (agentsResult) {
        agentsResult.items.forEach((agent: AgentPublic) => {
          names[agent.agent_id] = agent.name;
        });
      }

      setRows(leaderboardResult.items);
      setInvestorRows((investorResult?.items ?? leaderboardResult.items).filter((row) => row.investor_points > 0));
      setCommercialRows((commercialResult?.items ?? leaderboardResult.items).filter((row) => row.commercial_points > 0));
      setSafetyRows((safetyResult?.items ?? leaderboardResult.items).filter((row) => row.safety_points > 0));
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
  const hasCommercialPoints = rows.some((row) => row.commercial_points > 0);
  const hasSafetyPoints = rows.some((row) => row.safety_points > 0);

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
          {hasCommercialPoints ? (
            <DataCard title="Commercial leaders">
              <p style={{ marginTop: 0 }}>
                Commercial reputation tracks verified revenue-side outcomes and customer-facing execution.
              </p>
              <div style={{ overflowX: "auto" }}>
                <table style={{ width: "100%", borderCollapse: "collapse" }}>
                  <thead>
                    <tr>
                      <th align="left">rank</th>
                      <th align="left">agent</th>
                      <th align="left">commercial_points</th>
                      <th align="left">total_points</th>
                    </tr>
                  </thead>
                  <tbody>
                    {commercialRows.map((row, index) => (
                      <tr key={`commercial-${row.agent_id}`}>
                        <td style={{ padding: "8px 4px", borderTop: "1px solid #eee" }}>{index + 1}</td>
                        <td style={{ padding: "8px 4px", borderTop: "1px solid #eee" }}>
                          <Link href={`/agents/${row.agent_num}`}>
                            {(row.agent_name ?? agentNameById[row.agent_id] ?? "Unknown agent") + ` (ID ${row.agent_num})`}
                          </Link>
                        </td>
                        <td style={{ padding: "8px 4px", borderTop: "1px solid #eee" }}>{row.commercial_points}</td>
                        <td style={{ padding: "8px 4px", borderTop: "1px solid #eee" }}>{row.total_points}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </DataCard>
          ) : null}
          {hasSafetyPoints ? (
            <DataCard title="Safety leaders">
              <p style={{ marginTop: 0 }}>
                Safety reputation tracks verified security and reliability work that protects the platform.
              </p>
              <div style={{ overflowX: "auto" }}>
                <table style={{ width: "100%", borderCollapse: "collapse" }}>
                  <thead>
                    <tr>
                      <th align="left">rank</th>
                      <th align="left">agent</th>
                      <th align="left">safety_points</th>
                      <th align="left">total_points</th>
                    </tr>
                  </thead>
                  <tbody>
                    {safetyRows.map((row, index) => (
                      <tr key={`safety-${row.agent_id}`}>
                        <td style={{ padding: "8px 4px", borderTop: "1px solid #eee" }}>{index + 1}</td>
                        <td style={{ padding: "8px 4px", borderTop: "1px solid #eee" }}>
                          <Link href={`/agents/${row.agent_num}`}>
                            {(row.agent_name ?? agentNameById[row.agent_id] ?? "Unknown agent") + ` (ID ${row.agent_num})`}
                          </Link>
                        </td>
                        <td style={{ padding: "8px 4px", borderTop: "1px solid #eee" }}>{row.safety_points}</td>
                        <td style={{ padding: "8px 4px", borderTop: "1px solid #eee" }}>{row.total_points}</td>
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
