"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import { DataCard, PageContainer } from "@/components/Cards";
import { ErrorState } from "@/components/ErrorState";
import { EmptyState, Loading } from "@/components/State";
import { api, readErrorMessage, ApiError } from "@/lib/api";
import { getSurface } from "@/product_surfaces";
import type { ProjectDetail } from "@/types";

export default function AppBySlugPage({ params }: { params: { slug: string } }) {
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [project, setProject] = useState<ProjectDetail | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const result = await api.getProjectBySlug(params.slug);
      setProject(result);
    } catch (err) {
      if (err instanceof ApiError && err.status === 404) {
        setProject(null);
      } else {
        setError(readErrorMessage(err));
      }
    } finally {
      setLoading(false);
    }
  }, [params.slug]);

  useEffect(() => {
    void load();
  }, [load]);

  const Surface = project ? getSurface(project.slug) : null;

  return (
    <PageContainer title={`App / ${params.slug}`}>
      {loading ? <Loading message="Loading app surface..." /> : null}
      {!loading && error ? <ErrorState message={error} onRetry={load} /> : null}
      {!loading && !error && !project ? (
        <DataCard title="Not found">
          <EmptyState message="Project app not found." />
          <Link href="/apps">Back to apps</Link>
        </DataCard>
      ) : null}
      {!loading && !error && project ? (
        Surface ? (
          <Surface project={project} />
        ) : (
          <DataCard title={project.name}>
            <p>{project.description_md ?? "No project description yet."}</p>
            <ul>
              <li><Link href={`/projects/${project.project_id}`}>Open project page</Link></li>
              <li><Link href={`/bounties?project_id=${project.project_id}`}>View project bounties</Link></li>
              <li><Link href={`/discussions?scope=project&project_id=${project.project_id}`}>Join project discussions</Link></li>
            </ul>
            <p>Funding policy: project bounties are paid from project capital/revenue (not platform treasury).</p>
          </DataCard>
        )
      ) : null}
    </PageContainer>
  );
}
