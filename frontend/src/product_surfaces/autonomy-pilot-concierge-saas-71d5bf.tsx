import { TemplateSurface } from "./template";
import type { ProjectDetail } from "@/types";

export function AutonomyPilotConciergeSaas71d5bfSurface({ project }: { project: ProjectDetail }) {
  return (
    <TemplateSurface
      project={project}
      customTitle={"Autonomy Pilot: Concierge SaaS 71D5BF"}
      customTagline={"Autonomous pilot: funding, payout, and delivery verified on-chain."}
      customDescription={"Generated from the frontend bounty deliverable. This page summarizes the project state, treasury, funding, and linked work."}
      ctaLabel={"Open Project Workspace"}
      ctaHref={"/projects/proj_from_proposal_prp_4f01552188836881"}
    />
  );
}
