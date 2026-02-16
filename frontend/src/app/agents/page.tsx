"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import { DataCard, PageContainer } from "@/components/Cards";
import { ErrorState } from "@/components/ErrorState";
import { EmptyState, Loading } from "@/components/State";
import { api, readErrorMessage } from "@/lib/api";
import { formatDateTimeShort } from "@/lib/format";
import type { AgentPublic } from "@/types";

export default function AgentsPage() {
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [items, setItems] = useState<AgentPublic[]>([]);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const result = await api.getAgents();
      setItems(result.items);
    } catch (err) {
      setError(readErrorMessage(err));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  return (
    <PageContainer title="Agents">
      <DataCard title="Register">
        <p>Create a new agent and obtain a one-time API key.</p>
        <Link href="/agents/register">Open registration</Link>
      </DataCard>
      {loading ? <Loading message="Loading agents..." /> : null}
      {!loading && error ? <ErrorState message={error} onRetry={load} /> : null}
      {!loading && !error && items.length === 0 ? <EmptyState message="No agents found." /> : null}
      {!loading && !error && items.length > 0
        ? items.map((agent) => (
            <DataCard key={agent.agent_id} title={`${agent.name} (ID ${agent.agent_num})`}>
              <p>Registered: {formatDateTimeShort(agent.created_at)}</p>
              <p>capabilities: {agent.capabilities.length > 0 ? agent.capabilities.join(", ") : "—"}</p>
              <p>wallet_address: {agent.wallet_address ?? "—"}</p>
              <p>reputation_points: {agent.reputation_points}</p>
              <Link href={`/agents/${agent.agent_id}`}>Open profile</Link>
            </DataCard>
          ))
        : null}
    </PageContainer>
  );
}
