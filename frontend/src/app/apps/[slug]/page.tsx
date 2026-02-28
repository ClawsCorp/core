"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import { DataCard, PageContainer } from "@/components/Cards";
import { ErrorState } from "@/components/ErrorState";
import { EmptyState, Loading } from "@/components/State";
import { api, readErrorMessage, ApiError } from "@/lib/api";
import { formatDateTimeShort, formatMicroUsdc } from "@/lib/format";
import { getSurface } from "@/product_surfaces";
import { DemoSurface } from "@/product_surfaces/demo";
import type { ProjectDeliveryReceipt, ProjectDetail, ProjectFundingSummary } from "@/types";

export default function AppBySlugPage({ params }: { params: { slug: string } }) {
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [project, setProject] = useState<ProjectDetail | null>(null);
  const [deliveryReceipt, setDeliveryReceipt] = useState<ProjectDeliveryReceipt | null>(null);
  const [fundingSummary, setFundingSummary] = useState<ProjectFundingSummary | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const nextProject = await api.getProjectBySlug(params.slug);
      setProject(nextProject);
      try {
        const nextReceipt = await api.getProjectDeliveryReceipt(nextProject.project_id);
        setDeliveryReceipt(nextReceipt);
      } catch {
        setDeliveryReceipt(null);
      }
      try {
        const nextFunding = await api.getProjectFundingSummary(nextProject.project_id);
        setFundingSummary(nextFunding);
      } catch {
        setFundingSummary(null);
      }
    } catch (err) {
      if (err instanceof ApiError && err.status === 404) {
        setProject(null);
        setDeliveryReceipt(null);
        setFundingSummary(null);
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
        <>
          {deliveryReceipt ? (
            <DataCard title="Delivery status">
              <p>
                status: {deliveryReceipt.status} ({deliveryReceipt.items_ready}/{deliveryReceipt.items_total} ready)
              </p>
              <p>last computed: {formatDateTimeShort(deliveryReceipt.computed_at)}</p>
              {deliveryReceipt.items.length > 0 ? (
                <>
                  <p>latest deliverables:</p>
                  <ul>
                    {deliveryReceipt.items.slice(0, 2).map((item) => (
                      <li key={item.bounty_id}>
                        {item.title} ({item.status})
                        {item.git_accepted_merge_sha ? " [merged]" : ""}
                        {item.paid_tx_hash ? " [paid]" : ""}
                        {item.git_pr_url ? (
                          <>
                            {" "}
                            <Link href={item.git_pr_url}>PR</Link>
                          </>
                        ) : null}
                      </li>
                    ))}
                  </ul>
                </>
              ) : null}
              <p>
                <Link href={`/projects/${project.project_id}#delivery-receipt`}>Open full delivery receipt</Link>
              </p>
            </DataCard>
          ) : null}
          {fundingSummary ? (
            <DataCard title="Funding status">
              <p>raised: {formatMicroUsdc(fundingSummary.total_raised_micro_usdc)}</p>
              <p>open round: {fundingSummary.open_round ? fundingSummary.open_round.title ?? "Open" : "Closed"}</p>
              <p>current round raised: {formatMicroUsdc(fundingSummary.open_round_raised_micro_usdc)}</p>
              <p>contributors: {fundingSummary.contributors_total_count}</p>
              <p>last deposit: {formatDateTimeShort(fundingSummary.last_deposit_at)}</p>
              <p>
                <Link href={`/projects/${project.project_id}`}>Open full project operations</Link>
              </p>
            </DataCard>
          ) : null}
          {Surface ? <Surface project={project} /> : <DemoSurface project={project} />}
        </>
      ) : null}
    </PageContainer>
  );
}
