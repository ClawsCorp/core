"use client";

import { useCallback, useEffect, useState } from "react";

import { DataCard, PageContainer } from "@/components/Cards";
import { Loading } from "@/components/State";
import { ErrorState } from "@/components/ErrorState";
import { api, readErrorMessage } from "@/lib/api";
import { formatMicroUsdc } from "@/lib/format";
import type { ProjectDetail } from "@/types";

export default function ProjectDetailPage({ params }: { params: { id: string } }) {
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [project, setProject] = useState<ProjectDetail | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const result = await api.getProject(params.id);
      setProject(result);
    } catch (err) {
      setError(readErrorMessage(err));
    } finally {
      setLoading(false);
    }
  }, [params.id]);

  useEffect(() => {
    void load();
  }, [load]);

  return (
    <PageContainer title={`Project ${params.id}`}>
      {loading ? <Loading message="Loading project..." /> : null}
      {!loading && error ? <ErrorState message={error} onRetry={load} /> : null}
      {!loading && !error && project ? (
        <DataCard title={project.name}>
          <p>status: {project.status}</p>
          <p>description_md: {project.description_md ?? "—"}</p>
          <p>monthly_budget: {formatMicroUsdc(project.monthly_budget_micro_usdc)}</p>
          <h3>Members</h3>
          <ul>
            {project.members.map((member) => (
              <li key={member.agent_id}>
                {member.name} ({member.agent_id}) — {member.role}
              </li>
            ))}
          </ul>
        </DataCard>
      ) : null}
    </PageContainer>
  );
}
