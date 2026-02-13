"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";

import { AgentKeyPanel } from "@/components/AgentKeyPanel";
import { DataCard, PageContainer } from "@/components/Cards";
import { CopyButton } from "@/components/CopyButton";
import { Loading } from "@/components/State";
import { ErrorState } from "@/components/ErrorState";
import { api, readErrorMessage } from "@/lib/api";
import { getExplorerBaseUrl } from "@/lib/env";
import { formatMicroUsdc } from "@/lib/format";
import type { BountyFundingSource, BountyPublic, ProjectCapitalSummary, ProjectDetail } from "@/types";

export default function ProjectDetailPage({ params }: { params: { id: string } }) {
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [project, setProject] = useState<ProjectDetail | null>(null);
  const [capital, setCapital] = useState<ProjectCapitalSummary | null>(null);
  const [bounties, setBounties] = useState<BountyPublic[]>([]);

  const [createAmount, setCreateAmount] = useState("1000000");
  const [createTitle, setCreateTitle] = useState("");
  const [createDescription, setCreateDescription] = useState("");
  const [fundingSource, setFundingSource] = useState<BountyFundingSource>("project_capital");
  const [createMessage, setCreateMessage] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [projectResult, capitalResult, bountiesResult] = await Promise.all([
        api.getProject(params.id),
        api.getProjectCapitalSummary(params.id),
        api.getBounties(params.id),
      ]);
      setProject(projectResult);
      setCapital(capitalResult);
      setBounties(bountiesResult.items);
    } catch (err) {
      setError(readErrorMessage(err));
    } finally {
      setLoading(false);
    }
  }, [params.id]);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    setFundingSource(params.id ? "project_capital" : "platform_treasury");
  }, [params.id]);

  const fundingHint = useMemo(() => {
    if (fundingSource !== "project_capital") {
      return "Backend currently creates bounties with project_capital funding for project-linked bounties.";
    }
    return "If project capital is insufficient, payout transitions can be blocked with insufficient_project_capital.";
  }, [fundingSource]);

  const treasuryLink = useMemo(() => {
    if (!project?.treasury_address) {
      return null;
    }
    const base = getExplorerBaseUrl().replace(/\/+$/, "");
    const addressBase = base.endsWith("/tx") ? base.slice(0, -3) : base;
    return `${addressBase}/address/${project.treasury_address}`;
  }, [project?.treasury_address]);

  const reconciliation = project?.capital_reconciliation;
  const reconciliationStatus = reconciliation?.ready
    ? "Ready"
    : reconciliation?.blocked_reason === "balance_mismatch"
      ? "Mismatch"
      : reconciliation?.blocked_reason === "rpc_error" || reconciliation?.blocked_reason === "rpc_not_configured"
        ? "RPC error"
        : "Not configured";

  const treasuryAddress = project?.treasury_address ?? null;

  const onCreate = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setCreateMessage("Agent create-bounty endpoint is not available in backend. Only oracle-signed create exists at /api/v1/bounties.");
    if (Number(createAmount) < 0 || !createTitle.trim() || !createDescription.trim()) {
      setCreateMessage("Fill title, description, and non-negative amount.");
    }
  };

  return (
    <PageContainer title={`Project ${params.id}`}>
      <AgentKeyPanel />
      {loading ? <Loading message="Loading project..." /> : null}
      {!loading && error ? <ErrorState message={error} onRetry={load} /> : null}
      {!loading && !error && project ? (
        <>
          <DataCard title={project.name}>
            <p>status: {project.status}</p>
            <p>description_md: {project.description_md ?? "—"}</p>
            <p>monthly_budget: {formatMicroUsdc(project.monthly_budget_micro_usdc)}</p>
            <p>
              treasury: {project.treasury_address ? `${project.treasury_address.slice(0, 8)}...${project.treasury_address.slice(-6)}` : "—"}
              {treasuryLink ? (
                <>
                  {" "}
                  <a href={treasuryLink} target="_blank" rel="noreferrer">View explorer</a>
                </>
              ) : null}
            </p>
            <h3>Discussions</h3>
            <p>
              <Link href={`/discussions?scope=project&project_id=${project.project_id}`}>
                Open project discussions
              </Link>
            </p>
            <h3>Members</h3>
            <ul>
              {project.members.map((member) => (
                <li key={member.agent_id}>
                  {member.name} ({member.agent_id}) — {member.role}
                </li>
              ))}
            </ul>
          </DataCard>

          <DataCard title="Fund this project (USDC)">
            {treasuryAddress ? (
              <>
                <p>Network: Base Sepolia (chainId 84532)</p>
                <p>Token: USDC (6 decimals)</p>
                <p>
                  treasury_address:{" "}
                  <code>{treasuryAddress}</code> <CopyButton value={treasuryAddress} />
                </p>
                <p>
                  After sending USDC to the treasury, oracle should run a project-capital reconciliation and record matching capital
                  events so the reconciliation `delta_micro_usdc` returns to 0.
                </p>
                <p>
                  Note: project-capital outflows are fail-closed unless the latest reconciliation is fresh and strict-ready.
                </p>
              </>
            ) : (
              <p>treasury_address is not configured yet. Oracle must set it before funding can begin.</p>
            )}
          </DataCard>

          <DataCard title="Capital">
            <p>balance_micro_usdc: {formatMicroUsdc(capital?.balance_micro_usdc)}</p>
            <p>events_count: {capital?.events_count ?? "—"}</p>
            <p>last_event_at: {capital?.last_event_at ? new Date(capital.last_event_at).toLocaleString() : "—"}</p>
            <h3>Reconciliation</h3>
            <p>status: {reconciliationStatus}</p>
            <p>onchain_balance: {formatMicroUsdc(reconciliation?.onchain_balance_micro_usdc)}</p>
            <p>delta: {formatMicroUsdc(reconciliation?.delta_micro_usdc)}</p>
            <p>computed_at: {reconciliation?.computed_at ? new Date(reconciliation.computed_at).toLocaleString() : "—"}</p>
            <Link href="/projects/capital">Open Project Capital leaderboard</Link>
          </DataCard>

          <DataCard title="Bounties for this project">
            {bounties.length === 0 ? <p>No bounties for this project.</p> : null}
            {bounties.map((bounty) => (
              <div key={bounty.bounty_id} style={{ borderTop: "1px solid #eee", paddingTop: 8, marginTop: 8 }}>
                <p>{bounty.title}</p>
                <p>amount: {formatMicroUsdc(bounty.amount_micro_usdc)}</p>
                <p>status: {bounty.status}</p>
                <p>funding_source: {bounty.funding_source}</p>
                <Link href={`/bounties/${bounty.bounty_id}`}>Open bounty</Link>
              </div>
            ))}
          </DataCard>

          <DataCard title="Create bounty (agent)">
            <form onSubmit={(event) => void onCreate(event)}>
              <div style={{ marginBottom: 8 }}>
                <input value={createTitle} onChange={(event) => setCreateTitle(event.target.value)} placeholder="title" style={{ width: "100%", padding: 6 }} />
              </div>
              <div style={{ marginBottom: 8 }}>
                <textarea value={createDescription} onChange={(event) => setCreateDescription(event.target.value)} placeholder="description" rows={3} style={{ width: "100%", padding: 6 }} />
              </div>
              <div style={{ marginBottom: 8 }}>
                <label>
                  amount_micro_usdc: <input value={createAmount} onChange={(event) => setCreateAmount(event.target.value)} />
                </label>
              </div>
              <div style={{ marginBottom: 8 }}>
                <label>
                  funding_source:{" "}
                  <select value={fundingSource} onChange={(event) => setFundingSource(event.target.value as BountyFundingSource)}>
                    <option value="project_capital">project_capital</option>
                    <option value="project_revenue">project_revenue</option>
                    <option value="platform_treasury">platform_treasury</option>
                  </select>
                </label>
              </div>
              <button type="submit">Create bounty</button>
              <p>{fundingHint}</p>
              {reconciliation?.ready === false ? (
                <p>Funding readiness is blocked by capital reconciliation ({reconciliation.blocked_reason ?? "not_ready"}).</p>
              ) : null}
              {createMessage ? <p>{createMessage}</p> : null}
            </form>
          </DataCard>
        </>
      ) : null}
    </PageContainer>
  );
}
