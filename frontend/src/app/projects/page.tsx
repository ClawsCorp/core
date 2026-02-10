"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import { DataCard, PageContainer } from "@/components/Cards";
import { EmptyState, Loading } from "@/components/State";
import { ErrorState } from "@/components/ErrorState";
import { api, readErrorMessage } from "@/lib/api";
import { formatMicroUsdc } from "@/lib/format";
import type { ProjectSummary } from "@/types";

export default function ProjectsPage() {
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [items, setItems] = useState<ProjectSummary[]>([]);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const result = await api.getProjects();
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
    <PageContainer title="Projects">
      {loading ? <Loading message="Loading projects..." /> : null}
      {!loading && error ? <ErrorState message={error} onRetry={load} /> : null}
      {!loading && !error && items.length === 0 ? <EmptyState message="No projects found." /> : null}
      {!loading && !error && items.length > 0
        ? items.map((project) => (
            <DataCard key={project.project_id} title={project.name}>
              <p>project_id: {project.project_id}</p>
              <p>status: {project.status}</p>
              <p>monthly_budget: {formatMicroUsdc(project.monthly_budget_micro_usdc)}</p>
              <Link href={`/projects/${project.project_id}`}>Open detail</Link>
            </DataCard>
          ))
        : null}
    </PageContainer>
  );
}
