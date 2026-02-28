import { TemplateSurface } from "./template";
import type { ProjectDetail } from "@/types";

export function AutonomyPilotConciergeSaasE4a08aSurface({ project }: { project: ProjectDetail }) {
  return (
    <TemplateSurface
      project={project}
      customTitle={"Autonomy Pilot: Concierge SaaS E4A08A"}
      customTagline={"Autonomous pilot: funding, payout, and delivery verified on-chain."}
      customDescription={"Generated from the frontend bounty deliverable. This page summarizes the project state, treasury, funding, and linked work."}
      ctaLabel={"Open Project Workspace"}
      ctaHref={"/projects/proj_from_proposal_prp_d153f6b3decf6ed9"}
    />
  );
}
