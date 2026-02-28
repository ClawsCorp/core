import Link from "next/link";

import { DataCard } from "@/components/Cards";
import { formatMicroUsdc } from "@/lib/format";
import type { ProjectDetail } from "@/types";

export function TemplateSurface({
  project,
  customTitle,
  customTagline,
  customDescription,
  ctaLabel,
  ctaHref,
}: {
  project: ProjectDetail;
  customTitle?: string | null;
  customTagline?: string | null;
  customDescription?: string | null;
  ctaLabel?: string | null;
  ctaHref?: string | null;
}) {
  const title = customTitle || `Surface: ${project.name} (ID ${project.project_num})`;
  const tagline = customTagline || "Demo application surface for this project.";
  const description = customDescription || "This is a template surface. Copy this file and customize it for your project slug.";
  const primaryLabel = ctaLabel || "Open project page";
  const primaryHref = ctaHref || `/projects/${project.project_id}`;

  return (
    <DataCard title={title}>
      <p>{tagline}</p>
      <p>{description}</p>
      <p>slug: {project.slug}</p>
      <p>treasury: {project.treasury_address ?? "—"}</p>
      <p>
        reconciliation:{" "}
        {project.capital_reconciliation?.ready
          ? "Ready"
          : project.capital_reconciliation?.blocked_reason ?? "Missing"}
      </p>
      <p>onchain_balance: {formatMicroUsdc(project.capital_reconciliation?.onchain_balance_micro_usdc)}</p>
      <p>delta: {formatMicroUsdc(project.capital_reconciliation?.delta_micro_usdc)}</p>
      <ul>
        <li>
          <Link href={primaryHref}>{primaryLabel}</Link>
        </li>
        <li>
          <Link href={`/projects/${project.project_id}#delivery-receipt`}>View delivery receipt</Link>
        </li>
        <li>
          <Link href={`/bounties?project_id=${project.project_id}`}>View project bounties</Link>
        </li>
        <li>
          <Link href={`/discussions?scope=project&project_id=${project.project_id}`}>Join project discussions</Link>
        </li>
      </ul>
    </DataCard>
  );
}
