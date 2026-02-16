"use client";

import { useCallback, useEffect, useState } from "react";

import { DataCard, PageContainer } from "@/components/Cards";
import { ErrorState } from "@/components/ErrorState";
import { Loading } from "@/components/State";
import { api, readErrorMessage } from "@/lib/api";
import { formatDateTimeShort } from "@/lib/format";
import type { AgentPublic, ReputationAgentSummary } from "@/types";

export default function AgentDetailPage({ params }: { params: { agent_id: string } }) {
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [agent, setAgent] = useState<AgentPublic | null>(null);
  const [reputation, setReputation] = useState<ReputationAgentSummary | null>(null);
  const [reputationError, setReputationError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    setReputationError(null);

    try {
      const agentResult = await api.getAgent(params.agent_id);
      setAgent(agentResult);
    } catch (err) {
      setError(readErrorMessage(err));
      setLoading(false);
      return;
    }

    try {
      const repResult = await api.getReputationAgent(params.agent_id);
      setReputation(repResult);
    } catch {
      setReputation(null);
      setReputationError("Reputation unavailable");
    } finally {
      setLoading(false);
    }
  }, [params.agent_id]);

  useEffect(() => {
    void load();
  }, [load]);

  return (
    <PageContainer title="Agent profile">
      {loading ? <Loading message="Loading agent..." /> : null}
      {!loading && error ? <ErrorState message={error} onRetry={load} /> : null}
      {!loading && !error && agent ? (
        <>
          <DataCard title={`${agent.name} (ID ${agent.agent_num})`}>
            <p>capabilities: {agent.capabilities.length > 0 ? agent.capabilities.join(", ") : "—"}</p>
            <p>wallet_address: {agent.wallet_address ?? "—"}</p>
            <p>registered_at: {formatDateTimeShort(agent.created_at)}</p>
          </DataCard>

          <DataCard title="Reputation">
            {reputation ? (
              <>
                <p>total_points: {reputation.total_points}</p>
                {typeof reputation.events_count === "number" ? <p>events_count: {reputation.events_count}</p> : null}
                {reputation.last_event_at ? <p>last_event_at: {formatDateTimeShort(reputation.last_event_at)}</p> : null}
              </>
            ) : (
              <p>{reputationError ?? "Reputation unavailable"}</p>
            )}
          </DataCard>
        </>
      ) : null}
    </PageContainer>
  );
}
