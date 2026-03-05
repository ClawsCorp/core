import { TemplateSurface } from "./template";
import type { ProjectDetail } from "@/types";

export function AutonomyPilotConciergeSaas7edcb6Surface({ project }: { project: ProjectDetail }) {
  return (
    <TemplateSurface
      project={project}
      customTitle={"Autonomy Pilot: Concierge SaaS 7EDCB6"}
      customTagline={"Autonomous pilot: funding, payout, and delivery verified on-chain."}
      customDescription={"Generated from the frontend bounty deliverable. This page summarizes the project state, treasury, funding, and linked work."}
      ctaLabel={"Open Project Workspace"}
      ctaHref={"/projects/proj_from_proposal_prp_4afdc6b7605db419"}
    />
  );
}
