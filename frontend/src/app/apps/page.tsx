"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import { DataCard, PageContainer } from "@/components/Cards";
import { ErrorState } from "@/components/ErrorState";
import { EmptyState, Loading } from "@/components/State";
import { api, readErrorMessage } from "@/lib/api";
import type { ProjectSummary } from "@/types";

export default function AppsPage() {
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
    <PageContainer title="Project Apps">
      {loading ? <Loading message="Loading project apps..." /> : null}
      {!loading && error ? <ErrorState message={error} onRetry={load} /> : null}
      {!loading && !error && items.length === 0 ? <EmptyState message="No projects found." /> : null}
      {!loading && !error && items.length > 0
        ? items.map((project) => (
            <DataCard key={project.project_id} title={project.name}>
              <p>status: {project.status}</p>
              <p>slug: {project.slug}</p>
              <Link href={`/apps/${project.slug}`}>Open app surface</Link>
            </DataCard>
          ))
        : null}
    </PageContainer>
  );
}
