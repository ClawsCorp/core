import Link from "next/link";

import { DataCard } from "@/components/Cards";
import { formatMicroUsdc } from "@/lib/format";
import type { ProjectDetail } from "@/types";

export function TemplateSurface({ project }: { project: ProjectDetail }) {
  return (
    <DataCard title={`Surface: ${project.name} (ID ${project.project_num})`}>
      <p>This is a template surface. Copy this file and customize it for your project slug.</p>
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
          <Link href={`/projects/${project.project_id}`}>Open project page</Link>
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
