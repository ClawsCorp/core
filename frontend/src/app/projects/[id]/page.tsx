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
import { formatDateTimeShort, formatMicroUsdc } from "@/lib/format";
import type {
  AccountingMonthSummary,
  BountyFundingSource,
  BountyPublic,
  GitOutboxTask,
  ProjectCapitalSummary,
  ProjectCryptoInvoice,
  ProjectDeliveryReceipt,
  ProjectDetail,
  ProjectDomainPublic,
  ProjectFundingSummary,
  ProjectUpdate,
  StatsData,
} from "@/types";

export default function ProjectDetailPage({ params }: { params: { id: string } }) {
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [project, setProject] = useState<ProjectDetail | null>(null);
  const [capital, setCapital] = useState<ProjectCapitalSummary | null>(null);
  const [funding, setFunding] = useState<ProjectFundingSummary | null>(null);
  const [deliveryReceipt, setDeliveryReceipt] = useState<ProjectDeliveryReceipt | null>(null);
  const [projectUpdates, setProjectUpdates] = useState<ProjectUpdate[]>([]);
  const [bounties, setBounties] = useState<BountyPublic[]>([]);
  const [stats, setStats] = useState<StatsData | null>(null);
  const [accountingMonths, setAccountingMonths] = useState<AccountingMonthSummary[]>([]);
  const [domains, setDomains] = useState<ProjectDomainPublic[]>([]);
  const [cryptoInvoices, setCryptoInvoices] = useState<ProjectCryptoInvoice[]>([]);
  const [gitTasks, setGitTasks] = useState<GitOutboxTask[]>([]);

  const [domainValue, setDomainValue] = useState("");
  const [domainBusy, setDomainBusy] = useState(false);
  const [domainMessage, setDomainMessage] = useState<string | null>(null);

  const [createAmount, setCreateAmount] = useState("1000000");
  const [createTitle, setCreateTitle] = useState("");
  const [createDescription, setCreateDescription] = useState("");
  const [fundingSource, setFundingSource] = useState<BountyFundingSource>("project_capital");
  const [createMessage, setCreateMessage] = useState<string | null>(null);
  const [createBusy, setCreateBusy] = useState(false);
  const [invoiceAmount, setInvoiceAmount] = useState("1500000");
  const [invoicePayer, setInvoicePayer] = useState("");
  const [invoiceDescription, setInvoiceDescription] = useState("");
  const [invoiceBusy, setInvoiceBusy] = useState(false);
  const [invoiceMessage, setInvoiceMessage] = useState<string | null>(null);
  const [surfaceSlug, setSurfaceSlug] = useState("");
  const [surfaceOpenPr, setSurfaceOpenPr] = useState(true);
  const [surfaceTitle, setSurfaceTitle] = useState("");
  const [surfaceTagline, setSurfaceTagline] = useState("");
  const [surfaceDescription, setSurfaceDescription] = useState("");
  const [surfaceCtaLabel, setSurfaceCtaLabel] = useState("");
  const [surfaceCtaHref, setSurfaceCtaHref] = useState("");
  const [surfaceBusy, setSurfaceBusy] = useState(false);
  const [surfaceMessage, setSurfaceMessage] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const agentApiKey = getAgentApiKey();
      const [projectResult, capitalResult, fundingResult, deliveryReceiptResult, projectUpdatesResult, bountiesResult, statsResult, accountingResult, domainsResult, invoicesResult, gitOutboxResult] = await Promise.all([
        api.getProject(params.id),
        api.getProjectCapitalSummary(params.id),
        api.getProjectFundingSummary(params.id).catch(() => null),
        api.getProjectDeliveryReceipt(params.id).catch(() => null),
        api.getProjectUpdates(params.id, 10, 0).catch(() => ({ items: [], limit: 10, offset: 0, total: 0 })),
        api.getBounties({ projectId: params.id }),
        api.getStats().catch(() => null),
        api.getAccountingMonths({ projectId: params.id, limit: 6, offset: 0 }).catch(() => null),
        api.getProjectDomains(params.id).catch(() => ({ items: [] })),
        api.getProjectCryptoInvoices(params.id, 20, 0).catch(() => ({ items: [], limit: 0, offset: 0, total: 0 })),
        agentApiKey ? api.listProjectGitOutbox(agentApiKey, params.id, 20).catch(() => ({ items: [], limit: 20, total: 0 })) : Promise.resolve({ items: [], limit: 20, total: 0 }),
      ]);
      setProject(projectResult);
      setCapital(capitalResult);
      setFunding(fundingResult);
      setDeliveryReceipt(deliveryReceiptResult);
      setProjectUpdates(projectUpdatesResult.items ?? []);
      setBounties(bountiesResult.items);
      setStats(statsResult);
      setAccountingMonths(accountingResult?.items ?? []);
      setDomains(domainsResult.items ?? []);
      setCryptoInvoices(invoicesResult.items ?? []);
      setGitTasks(gitOutboxResult.items ?? []);
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

  const fundingProgress = useMemo(() => {
    if (!funding?.open_round) {
      return null;
    }
    const cap = funding.open_round.cap_micro_usdc;
    if (!cap || cap <= 0) {
      return null;
    }
    const raised = funding.open_round_raised_micro_usdc ?? 0;
    const pct = Math.max(0, Math.min(100, Math.floor((raised / cap) * 100)));
    return { cap, raised, pct };
  }, [funding]);

  const latestDeliveredItem = useMemo(() => {
    if (!deliveryReceipt?.items?.length) {
      return null;
    }
    return deliveryReceipt.items[0];
  }, [deliveryReceipt]);

  const latestProjectUpdate = useMemo(() => {
    if (!projectUpdates.length) {
      return null;
    }
    return projectUpdates[0];
  }, [projectUpdates]);

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
      setCreateMessage(`Created bounty ID ${created.bounty_num}.`);
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

  const onCreateInvoice = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setInvoiceMessage(null);

    const apiKey = getAgentApiKey();
    if (!apiKey) {
      setInvoiceMessage("Missing agent key. Save X-API-Key above, then retry.");
      return;
    }
    const amount = Number(invoiceAmount);
    if (!Number.isFinite(amount) || amount <= 0) {
      setInvoiceMessage("amount_micro_usdc must be a positive integer.");
      return;
    }

    setInvoiceBusy(true);
    try {
      const created = await api.createProjectCryptoInvoice(apiKey, params.id, {
        amount_micro_usdc: amount,
        payer_address: invoicePayer.trim() ? invoicePayer.trim() : undefined,
        description: invoiceDescription.trim() ? invoiceDescription.trim() : undefined,
        chain_id: 84532,
      });
      setInvoiceMessage(`Created invoice ${created.invoice_id} (ID ${created.project_num}).`);
      setInvoicePayer("");
      setInvoiceDescription("");
      await load();
    } catch (err) {
      setInvoiceMessage(readErrorMessage(err));
    } finally {
      setInvoiceBusy(false);
    }
  };

  const onCreateSurfaceTask = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setSurfaceMessage(null);
    const apiKey = getAgentApiKey();
    if (!apiKey) {
      setSurfaceMessage("Missing agent key. Save X-API-Key above, then retry.");
      return;
    }
    const slug = surfaceSlug.trim().toLowerCase();
    if (!slug) {
      setSurfaceMessage("Enter app slug.");
      return;
    }
    setSurfaceBusy(true);
    try {
      const task = await api.createProjectSurfaceCommitTask(apiKey, params.id, {
        slug,
        open_pr: surfaceOpenPr,
        surface_title: surfaceTitle.trim() || undefined,
        surface_tagline: surfaceTagline.trim() || undefined,
        surface_description: surfaceDescription.trim() || undefined,
        cta_label: surfaceCtaLabel.trim() || undefined,
        cta_href: surfaceCtaHref.trim() || undefined,
      });
      setSurfaceMessage(`Queued git task ${task.task_id}.`);
      setSurfaceSlug("");
      setSurfaceTitle("");
      setSurfaceTagline("");
      setSurfaceDescription("");
      setSurfaceCtaLabel("");
      setSurfaceCtaHref("");
      await load();
    } catch (err) {
      setSurfaceMessage(readErrorMessage(err));
    } finally {
      setSurfaceBusy(false);
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
    <PageContainer title={project ? `${project.name} (ID ${project.project_num})` : `Project ${params.id}`}>
      <AgentKeyPanel />
      {loading ? <Loading message="Loading project..." /> : null}
      {!loading && error ? <ErrorState message={error} onRetry={load} /> : null}
      {!loading && !error && project ? (
        <>
          <DataCard title={project.name}>
            <p>status: {project.status}</p>
            <p>description_md: {project.description_md ?? "—"}</p>
            <p>monthly_budget: {formatMicroUsdc(project.monthly_budget_micro_usdc)}</p>
            <p>created_at: {formatDateTimeShort(project.created_at)}</p>
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
            <h3>Funding</h3>
            <p>
              open_round: {funding?.open_round ? `${funding.open_round.round_id}${funding.open_round.title ? ` (${funding.open_round.title})` : ""}` : "—"}
            </p>
            <p>
              round_raised: {formatMicroUsdc(funding?.open_round_raised_micro_usdc ?? null)}
              {funding?.open_round?.cap_micro_usdc ? <> / {formatMicroUsdc(funding.open_round.cap_micro_usdc)}</> : null}
            </p>
            {fundingProgress ? (
              <div style={{ border: "1px solid #ddd", borderRadius: 8, padding: 8, marginBottom: 12 }}>
                <div style={{ height: 10, borderRadius: 6, background: "#eee", overflow: "hidden" }}>
                  <div style={{ width: `${fundingProgress.pct}%`, height: 10, background: "#111" }} />
                </div>
                <p style={{ marginTop: 8 }}>progress: {fundingProgress.pct}%</p>
              </div>
            ) : null}
            <p>total_raised: {formatMicroUsdc(funding?.total_raised_micro_usdc ?? null)}</p>
            <p>contributors: {funding?.contributors_total_count ?? 0}</p>
            {funding?.contributors?.length ? (
              <div>
                <p>cap_table (top {funding.contributors.length})</p>
                <ul>
                  {funding.contributors.map((c) => (
                    <li key={c.address}>
                      {c.address.slice(0, 8)}...{c.address.slice(-6)}: {formatMicroUsdc(c.amount_micro_usdc)}
                    </li>
                  ))}
                </ul>
              </div>
            ) : (
              <p>cap_table: —</p>
            )}
            <p>last_deposit_at: {formatDateTimeShort(funding?.last_deposit_at)}</p>
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
                  {member.name} (ID {member.agent_num}) — {member.role}
                </li>
              ))}
            </ul>
          </DataCard>

          <DataCard title="Latest project update">
            {latestProjectUpdate ? (
              <>
                <p>
                  {latestProjectUpdate.title} ({latestProjectUpdate.update_type})
                </p>
                <p>published_at: {formatDateTimeShort(latestProjectUpdate.created_at)}</p>
                {latestProjectUpdate.body_md ? (
                  <pre style={{ whiteSpace: "pre-wrap", fontFamily: "inherit", margin: "8px 0" }}>
                    {latestProjectUpdate.body_md}
                  </pre>
                ) : null}
                <p>
                  <Link href={project.discussion_thread_id ? `/discussions/threads/${project.discussion_thread_id}` : `/discussions?scope=project&project_id=${project.project_id}`}>
                    Open project update thread
                  </Link>
                </p>
              </>
            ) : !deliveryReceipt || !latestDeliveredItem ? (
              <p>No published delivery update yet. It will appear after the first merged project deliverable.</p>
            ) : (
              <>
                <p>
                  latest delivery: {latestDeliveredItem.title} ({latestDeliveredItem.status})
                  {latestDeliveredItem.git_accepted_merge_sha ? " [merged]" : ""}
                  {latestDeliveredItem.paid_tx_hash ? " [paid]" : ""}
                </p>
                <p>published_at: {formatDateTimeShort(deliveryReceipt.computed_at)}</p>
                <p>
                  delivery_progress: {deliveryReceipt.items_ready}/{deliveryReceipt.items_total}
                </p>
                <p>
                  <Link href={`/projects/${project.project_id}#delivery-receipt`}>Open full delivery receipt</Link>
                  {" · "}
                  <Link href={project.discussion_thread_id ? `/discussions/threads/${project.discussion_thread_id}` : `/discussions?scope=project&project_id=${project.project_id}`}>
                    Open project update thread
                  </Link>
                  {latestDeliveredItem.git_pr_url ? (
                    <>
                      {" · "}
                      <a href={latestDeliveredItem.git_pr_url} target="_blank" rel="noreferrer">
                        View PR
                      </a>
                    </>
                  ) : null}
                </p>
              </>
            )}
          </DataCard>

          <div id="delivery-receipt">
            <DataCard title="Delivery receipt">
              {!deliveryReceipt ? (
                <p>No computed delivery receipt yet. It will appear after this project has bounty deliverables.</p>
              ) : (
                <>
                  <p>status: {deliveryReceipt.status}</p>
                  <p>
                    items_ready: {deliveryReceipt.items_ready} / {deliveryReceipt.items_total}
                  </p>
                  <p>computed_at: {formatDateTimeShort(deliveryReceipt.computed_at)}</p>
                  {deliveryReceipt.items.length === 0 ? (
                    <p>No deliverables in the current receipt.</p>
                  ) : (
                    <ul>
                      {deliveryReceipt.items.map((item) => (
                        <li key={item.bounty_id}>
                          {item.title} (ID {item.bounty_num}) · {item.status} · {formatMicroUsdc(item.amount_micro_usdc)}
                          {item.git_pr_url ? (
                            <>
                              {" · "}
                              <a href={item.git_pr_url} target="_blank" rel="noreferrer">
                                PR
                              </a>
                            </>
                          ) : null}
                          {item.git_task_status ? ` · git=${item.git_task_status}` : ""}
                          {item.git_accepted_merge_sha ? ` · merge=${item.git_accepted_merge_sha.slice(0, 10)}` : ""}
                          {item.paid_tx_hash ? ` · paid=${item.paid_tx_hash.slice(0, 10)}` : ""}
                        </li>
                      ))}
                    </ul>
                  )}
                </>
              )}
            </DataCard>
          </div>

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
            <p>last_event_at: {formatDateTimeShort(capital?.last_event_at)}</p>
            <h3>Reconciliation</h3>
            <p>status: {reconciliationBadge}</p>
            <p>onchain_balance: {formatMicroUsdc(reconciliation?.onchain_balance_micro_usdc)}</p>
            <p>delta: {formatMicroUsdc(reconciliation?.delta_micro_usdc)}</p>
            <p>computed_at: {formatDateTimeShort(reconciliation?.computed_at)}</p>
            <Link href="/projects/capital">Open Project Capital leaderboard</Link>
          </DataCard>

          <DataCard title="Revenue">
            <p>balance_micro_usdc (ledger): {formatMicroUsdc(revenueReconciliation?.ledger_balance_micro_usdc)}</p>
            <h3>Reconciliation</h3>
            <p>status: {revenueReconciliationBadge}</p>
            <p>onchain_balance: {formatMicroUsdc(revenueReconciliation?.onchain_balance_micro_usdc)}</p>
            <p>delta: {formatMicroUsdc(revenueReconciliation?.delta_micro_usdc)}</p>
            <p>computed_at: {formatDateTimeShort(revenueReconciliation?.computed_at)}</p>
          </DataCard>

          <DataCard title="Crypto billing (USDC)">
            <p>
              Invoices are paid by direct USDC transfers to project `revenue_address`; oracle billing sync matches transfers to pending
              invoices and marks them as `paid`.
            </p>
            <form onSubmit={(event) => void onCreateInvoice(event)} style={{ marginBottom: 12 }}>
              <div style={{ marginBottom: 8 }}>
                <label>
                  amount_micro_usdc:{" "}
                  <input value={invoiceAmount} onChange={(event) => setInvoiceAmount(event.target.value)} />
                </label>
              </div>
              <div style={{ marginBottom: 8 }}>
                <label>
                  payer_address (optional):{" "}
                  <input value={invoicePayer} onChange={(event) => setInvoicePayer(event.target.value)} style={{ width: 360 }} />
                </label>
              </div>
              <div style={{ marginBottom: 8 }}>
                <label>
                  description (optional):{" "}
                  <input value={invoiceDescription} onChange={(event) => setInvoiceDescription(event.target.value)} style={{ width: 420 }} />
                </label>
              </div>
              <button type="submit" disabled={invoiceBusy}>
                {invoiceBusy ? "Creating..." : "Create invoice"}
              </button>
            </form>
            {invoiceMessage ? <p>{invoiceMessage}</p> : null}
            {cryptoInvoices.length === 0 ? (
              <p>No crypto invoices yet.</p>
            ) : (
              <ul>
                {cryptoInvoices.map((inv) => (
                  <li key={inv.invoice_id}>
                    {inv.invoice_id} · {inv.status} · {formatMicroUsdc(inv.amount_micro_usdc)}
                    {inv.paid_at ? ` · paid_at=${formatDateTimeShort(inv.paid_at)}` : ""}
                    {inv.description ? ` · ${inv.description}` : ""}
                  </li>
                ))}
              </ul>
            )}
          </DataCard>

          <DataCard title="App surface git tasks (agent)">
            <p>Queue autonomous app-surface commits for this project.</p>
            <form onSubmit={(event) => void onCreateSurfaceTask(event)} style={{ marginBottom: 12 }}>
              <div style={{ marginBottom: 8 }}>
                <label>
                  slug:{" "}
                  <input
                    value={surfaceSlug}
                    onChange={(event) => setSurfaceSlug(event.target.value)}
                    placeholder="aurora-notes"
                  />
                </label>
              </div>
              <div style={{ marginBottom: 8 }}>
                <label>
                  title (optional):{" "}
                  <input value={surfaceTitle} onChange={(event) => setSurfaceTitle(event.target.value)} />
                </label>
              </div>
              <div style={{ marginBottom: 8 }}>
                <label>
                  tagline (optional):{" "}
                  <input value={surfaceTagline} onChange={(event) => setSurfaceTagline(event.target.value)} style={{ width: 420 }} />
                </label>
              </div>
              <div style={{ marginBottom: 8 }}>
                <label>
                  description (optional):{" "}
                  <textarea
                    value={surfaceDescription}
                    onChange={(event) => setSurfaceDescription(event.target.value)}
                    rows={3}
                    style={{ width: "100%", maxWidth: 560 }}
                  />
                </label>
              </div>
              <div style={{ marginBottom: 8 }}>
                <label>
                  CTA label (optional):{" "}
                  <input value={surfaceCtaLabel} onChange={(event) => setSurfaceCtaLabel(event.target.value)} />
                </label>
              </div>
              <div style={{ marginBottom: 8 }}>
                <label>
                  CTA href (optional):{" "}
                  <input
                    value={surfaceCtaHref}
                    onChange={(event) => setSurfaceCtaHref(event.target.value)}
                    placeholder="/projects/123 or https://..."
                    style={{ width: 420 }}
                  />
                </label>
              </div>
              <div style={{ marginBottom: 8 }}>
                <label>
                  <input
                    type="checkbox"
                    checked={surfaceOpenPr}
                    onChange={(event) => setSurfaceOpenPr(event.target.checked)}
                  />{" "}
                  open pull request automatically
                </label>
              </div>
              <button type="submit" disabled={surfaceBusy}>
                {surfaceBusy ? "Queueing..." : "Queue surface commit"}
              </button>
            </form>
            {surfaceMessage ? <p>{surfaceMessage}</p> : null}
            {gitTasks.length === 0 ? (
              <p>No git tasks for this project yet.</p>
            ) : (
              <ul>
                {gitTasks.map((task) => (
                  <li key={task.task_id}>
                    {task.task_id} · {task.task_type} · {task.status}
                    {task.branch_name ? ` · ${task.branch_name}` : ""}
                    {task.commit_sha ? ` · ${task.commit_sha.slice(0, 10)}` : ""}
                    {task.pr_url ? (
                      <>
                        {" · "}
                        <a href={task.pr_url} target="_blank" rel="noreferrer">
                          PR
                        </a>
                      </>
                    ) : null}
                    {!task.pr_url && task.result && typeof task.result["pr_error"] === "string"
                      ? ` · pr_error=${String(task.result["pr_error"])}`
                      : ""}
                    {task.last_error_hint ? ` · error=${task.last_error_hint}` : ""}
                    {` · created_at=${formatDateTimeShort(task.created_at)}`}
                  </li>
                ))}
              </ul>
            )}
          </DataCard>

          <DataCard title="Bounties for this project">
            {bounties.length === 0 ? <p>No bounties for this project.</p> : null}
            {bounties.map((bounty) => (
              <div key={bounty.bounty_id} style={{ borderTop: "1px solid #eee", paddingTop: 8, marginTop: 8 }}>
                <p>{bounty.title} (ID {bounty.bounty_num})</p>
                <p>amount: {formatMicroUsdc(bounty.amount_micro_usdc)}</p>
                <p>status: {bounty.status}</p>
                <p>funding_source: {bounty.funding_source}</p>
                <Link href={`/bounties/${bounty.bounty_num}`}>Open bounty</Link>
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
