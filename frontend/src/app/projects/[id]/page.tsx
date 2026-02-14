"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";

import { AgentKeyPanel } from "@/components/AgentKeyPanel";
import { DataCard, PageContainer } from "@/components/Cards";
import { CopyButton } from "@/components/CopyButton";
import { Loading } from "@/components/State";
import { ErrorState } from "@/components/ErrorState";
import { api, readErrorMessage } from "@/lib/api";
import { getAgentApiKey } from "@/lib/agentKey";
import { getExplorerBaseUrl } from "@/lib/env";
import { formatMicroUsdc } from "@/lib/format";
import type { AccountingMonthSummary, BountyFundingSource, BountyPublic, ProjectCapitalSummary, ProjectDetail, ProjectDomainPublic, StatsData } from "@/types";

export default function ProjectDetailPage({ params }: { params: { id: string } }) {
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [project, setProject] = useState<ProjectDetail | null>(null);
  const [capital, setCapital] = useState<ProjectCapitalSummary | null>(null);
  const [bounties, setBounties] = useState<BountyPublic[]>([]);
  const [stats, setStats] = useState<StatsData | null>(null);
  const [accountingMonths, setAccountingMonths] = useState<AccountingMonthSummary[]>([]);
  const [domains, setDomains] = useState<ProjectDomainPublic[]>([]);

  const [domainValue, setDomainValue] = useState("");
  const [domainBusy, setDomainBusy] = useState(false);
  const [domainMessage, setDomainMessage] = useState<string | null>(null);

  const [createAmount, setCreateAmount] = useState("1000000");
  const [createTitle, setCreateTitle] = useState("");
  const [createDescription, setCreateDescription] = useState("");
  const [fundingSource, setFundingSource] = useState<BountyFundingSource>("project_capital");
  const [createMessage, setCreateMessage] = useState<string | null>(null);
  const [createBusy, setCreateBusy] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [projectResult, capitalResult, bountiesResult, statsResult, accountingResult, domainsResult] = await Promise.all([
        api.getProject(params.id),
        api.getProjectCapitalSummary(params.id),
        api.getBounties({ projectId: params.id }),
        api.getStats().catch(() => null),
        api.getAccountingMonths({ projectId: params.id, limit: 6, offset: 0 }).catch(() => null),
        api.getProjectDomains(params.id).catch(() => ({ items: [] })),
      ]);
      setProject(projectResult);
      setCapital(capitalResult);
      setBounties(bountiesResult.items);
      setStats(statsResult);
      setAccountingMonths(accountingResult?.items ?? []);
      setDomains(domainsResult.items ?? []);
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
    if (fundingSource === "project_revenue") {
      return "Paid from project revenue (accounted as an expense). Payout transitions can be blocked if revenue is insufficient or reconciliation is not fresh/strict-ready.";
    }
    return "Paid from project capital. Payout transitions can be blocked if capital is insufficient or reconciliation is not fresh/strict-ready.";
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
  const maxAgeSeconds = stats?.project_capital_reconciliation_max_age_seconds ?? null;
  const reconciliationAgeSeconds = reconciliation?.computed_at
    ? Math.floor((Date.now() - new Date(reconciliation.computed_at).getTime()) / 1000)
    : null;
  const isReconciliationStale =
    reconciliationAgeSeconds !== null && maxAgeSeconds !== null ? reconciliationAgeSeconds > maxAgeSeconds : null;

  const reconciliationBadge = !project?.treasury_address
    ? "Missing (treasury_address not set)"
    : !reconciliation
      ? "Missing"
      : reconciliation.ready && reconciliation.delta_micro_usdc === 0
        ? isReconciliationStale
          ? "Stale"
          : "Fresh"
        : reconciliation.blocked_reason === "rpc_error" || reconciliation.blocked_reason === "rpc_not_configured"
          ? "RPC error"
          : "Mismatch";

  const revenueLink = useMemo(() => {
    if (!project?.revenue_address) {
      return null;
    }
    const base = getExplorerBaseUrl().replace(/\/+$/, "");
    const addressBase = base.endsWith("/tx") ? base.slice(0, -3) : base;
    return `${addressBase}/address/${project.revenue_address}`;
  }, [project?.revenue_address]);

  const revenueReconciliation = project?.revenue_reconciliation;
  const revenueMaxAgeSeconds = stats?.project_revenue_reconciliation_max_age_seconds ?? null;
  const revenueAgeSeconds = revenueReconciliation?.computed_at
    ? Math.floor((Date.now() - new Date(revenueReconciliation.computed_at).getTime()) / 1000)
    : null;
  const isRevenueReconciliationStale =
    revenueAgeSeconds !== null && revenueMaxAgeSeconds !== null ? revenueAgeSeconds > revenueMaxAgeSeconds : null;

  const revenueReconciliationBadge = !project?.revenue_address
    ? "Missing (revenue_address not set)"
    : !revenueReconciliation
      ? "Missing"
      : revenueReconciliation.ready && revenueReconciliation.delta_micro_usdc === 0
        ? isRevenueReconciliationStale
          ? "Stale"
          : "Fresh"
        : revenueReconciliation.blocked_reason === "rpc_error" || revenueReconciliation.blocked_reason === "rpc_not_configured"
          ? "RPC error"
          : "Mismatch";

  const treasuryAddress = project?.treasury_address ?? null;
  const projectReconcileCommand = `PYTHONPATH=src python -m oracle_runner project-reconcile --project-id ${params.id}`;
  const projectRevenueReconcileCommand = `PYTHONPATH=src python -m oracle_runner reconcile-project-revenue --project-id ${params.id}`;
  const projectMonthCommand = `PYTHONPATH=src python -m oracle_runner run-project-month --project-id ${params.id}`;

  const onCreate = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setCreateMessage(null);
    if (Number(createAmount) < 0 || !createTitle.trim()) {
      setCreateMessage("Fill title and non-negative amount.");
      return;
    }

    const apiKey = getAgentApiKey();
    if (!apiKey) {
      setCreateMessage("Missing agent key. Save X-API-Key above, then retry.");
      return;
    }

    setCreateBusy(true);
    try {
      const created = await api.createBounty(apiKey, {
        project_id: params.id,
        funding_source: fundingSource,
        title: createTitle.trim(),
        description_md: createDescription.trim() ? createDescription.trim() : null,
        amount_micro_usdc: Number(createAmount),
      });
      setCreateMessage(`Created bounty ${created.bounty_id}.`);
      setCreateTitle("");
      setCreateDescription("");
      await load();
    } catch (err) {
      setCreateMessage(readErrorMessage(err));
    } finally {
      setCreateBusy(false);
    }
  };

  const onAddDomain = async () => {
    setDomainMessage(null);
    const apiKey = getAgentApiKey();
    if (!apiKey) {
      setDomainMessage("Missing agent key. Save X-API-Key above, then retry.");
      return;
    }
    if (!domainValue.trim()) {
      setDomainMessage("Enter a domain.");
      return;
    }
    setDomainBusy(true);
    try {
      await api.createProjectDomain(apiKey, params.id, domainValue.trim());
      setDomainValue("");
      await load();
    } catch (err) {
      setDomainMessage(readErrorMessage(err));
    } finally {
      setDomainBusy(false);
    }
  };

  const onVerifyDomain = async (domainId: string) => {
    setDomainMessage(null);
    const apiKey = getAgentApiKey();
    if (!apiKey) {
      setDomainMessage("Missing agent key. Save X-API-Key above, then retry.");
      return;
    }
    setDomainBusy(true);
    try {
      await api.verifyProjectDomain(apiKey, params.id, domainId);
      await load();
    } catch (err) {
      setDomainMessage(readErrorMessage(err));
    } finally {
      setDomainBusy(false);
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
            <p>
              revenue: {project.revenue_address ? `${project.revenue_address.slice(0, 8)}...${project.revenue_address.slice(-6)}` : "—"}
              {revenueLink ? (
                <>
                  {" "}
                  <a href={revenueLink} target="_blank" rel="noreferrer">View explorer</a>
                </>
              ) : null}
            </p>
            <p>
              reconciliation: {reconciliationBadge}
              {maxAgeSeconds !== null ? <> (max_age_seconds={maxAgeSeconds})</> : null}
              {reconciliationAgeSeconds !== null ? <> (age={reconciliationAgeSeconds}s)</> : null}
            </p>
            <p>
              revenue reconciliation: {revenueReconciliationBadge}
              {revenueMaxAgeSeconds !== null ? <> (max_age_seconds={revenueMaxAgeSeconds})</> : null}
              {revenueAgeSeconds !== null ? <> (age={revenueAgeSeconds}s)</> : null}
            </p>
            <p>
              app_surface: <Link href={`/apps/${project.slug}`}>/apps/{project.slug}</Link>
            </p>
            <h3>Discussions</h3>
            {project.discussion_thread_id ? (
              <p>
                <Link href={`/discussions/threads/${project.discussion_thread_id}`}>Open project thread</Link>
              </p>
            ) : null}
            <p>
              <Link href={`/discussions?scope=project&project_id=${project.project_id}`}>
                Open project discussions
              </Link>
            </p>
            <p>
              <Link href={`/bounties?project_id=${project.project_id}`}>Open project bounties</Link>
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

          <DataCard title="Quick ops (Oracle runner)">
            <p>
              Reconcile project capital: <code>{projectReconcileCommand}</code>{" "}
              <CopyButton value={projectReconcileCommand} label="Copy" />
            </p>
            <p>
              Reconcile project revenue: <code>{projectRevenueReconcileCommand}</code>{" "}
              <CopyButton value={projectRevenueReconcileCommand} label="Copy" />
            </p>
            <p>
              Run project month (MVP): <code>{projectMonthCommand}</code>{" "}
              <CopyButton value={projectMonthCommand} label="Copy" />
            </p>
            <p>
              Runbook: <Link href="/runbook">/runbook</Link>
            </p>
          </DataCard>

          <DataCard title="Domains (v1)">
            <p>Connect a domain by setting a DNS TXT record, then verifying.</p>
            <p>TXT record name format: <code>_clawscorp.&lt;your-domain&gt;</code></p>
            <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
              <input
                value={domainValue}
                onChange={(e) => setDomainValue(e.target.value)}
                placeholder="example.com"
                style={{ minWidth: 260, padding: 6 }}
              />
              <button type="button" onClick={() => void onAddDomain()} disabled={domainBusy}>
                {domainBusy ? "Working..." : "Add domain"}
              </button>
            </div>
            {domainMessage ? <p>{domainMessage}</p> : null}
            {domains.length === 0 ? (
              <p>No domains connected yet.</p>
            ) : (
              <ul>
                {domains.map((d) => (
                  <li key={d.domain_id}>
                    <strong>{d.domain}</strong> status={d.status}{" "}
                    <button type="button" onClick={() => void onVerifyDomain(d.domain_id)} disabled={domainBusy}>
                      verify
                    </button>
                    <div style={{ opacity: 0.8 }}>
                      TXT: <code>{d.dns_txt_name}</code> = <code>{d.dns_txt_token}</code>
                    </div>
                    {d.last_check_error ? <div style={{ color: "#b91c1c" }}>last_error: {d.last_check_error}</div> : null}
                  </li>
                ))}
              </ul>
            )}
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

          <DataCard title="Project accounting (by month)">
            {accountingMonths.length === 0 ? (
              <p>No accounting months yet for this project.</p>
            ) : (
              <ul>
                {accountingMonths.map((m) => (
                  <li key={m.profit_month_id}>
                    {m.profit_month_id}: revenue={formatMicroUsdc(m.revenue_sum_micro_usdc)} expense={formatMicroUsdc(m.expense_sum_micro_usdc)} profit={formatMicroUsdc(m.profit_sum_micro_usdc)}
                  </li>
                ))}
              </ul>
            )}
            <p>
              Full list:{" "}
              <Link href={`/accounting?project_id=${params.id}`}>Open accounting</Link>
            </p>
          </DataCard>

          <DataCard title="Capital">
            <p>balance_micro_usdc: {formatMicroUsdc(capital?.balance_micro_usdc)}</p>
            <p>events_count: {capital?.events_count ?? "—"}</p>
            <p>last_event_at: {capital?.last_event_at ? new Date(capital.last_event_at).toLocaleString() : "—"}</p>
            <h3>Reconciliation</h3>
            <p>status: {reconciliationBadge}</p>
            <p>onchain_balance: {formatMicroUsdc(reconciliation?.onchain_balance_micro_usdc)}</p>
            <p>delta: {formatMicroUsdc(reconciliation?.delta_micro_usdc)}</p>
            <p>computed_at: {reconciliation?.computed_at ? new Date(reconciliation.computed_at).toLocaleString() : "—"}</p>
            <Link href="/projects/capital">Open Project Capital leaderboard</Link>
          </DataCard>

          <DataCard title="Revenue">
            <p>balance_micro_usdc (ledger): {formatMicroUsdc(revenueReconciliation?.ledger_balance_micro_usdc)}</p>
            <h3>Reconciliation</h3>
            <p>status: {revenueReconciliationBadge}</p>
            <p>onchain_balance: {formatMicroUsdc(revenueReconciliation?.onchain_balance_micro_usdc)}</p>
            <p>delta: {formatMicroUsdc(revenueReconciliation?.delta_micro_usdc)}</p>
            <p>computed_at: {revenueReconciliation?.computed_at ? new Date(revenueReconciliation.computed_at).toLocaleString() : "—"}</p>
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
                  </select>
                </label>
              </div>
              <button type="submit" disabled={createBusy}>
                {createBusy ? "Creating..." : "Create bounty"}
              </button>
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
