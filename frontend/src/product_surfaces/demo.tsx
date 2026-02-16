/* eslint-disable react/no-unescaped-entities */
"use client";

import Link from "next/link";
import type { ReactNode } from "react";
import { useEffect, useMemo, useState } from "react";

import { api, readErrorMessage } from "@/lib/api";
import { getExplorerBaseUrl } from "@/lib/env";
import { formatMicroUsdc } from "@/lib/format";
import type {
  BountyPublic,
  DiscussionPost,
  DiscussionThreadSummary,
  ProjectCapitalSummary,
  ProjectDetail,
  ProjectFundingSummary,
  StatsData,
} from "@/types";

function Badge({ tone, children }: { tone: "green" | "yellow" | "red" | "gray"; children: ReactNode }) {
  const style: Record<string, string | number> = {
    display: "inline-block",
    padding: "2px 8px",
    borderRadius: 999,
    fontSize: 12,
    lineHeight: "18px",
    border: "1px solid #e5e7eb",
    background: "#f9fafb",
    color: "#111827",
  };

  if (tone === "green") style.background = "#ecfdf5";
  if (tone === "green") style.border = "1px solid #a7f3d0";
  if (tone === "green") style.color = "#065f46";

  if (tone === "yellow") style.background = "#fffbeb";
  if (tone === "yellow") style.border = "1px solid #fde68a";
  if (tone === "yellow") style.color = "#92400e";

  if (tone === "red") style.background = "#fef2f2";
  if (tone === "red") style.border = "1px solid #fecaca";
  if (tone === "red") style.color = "#991b1b";

  if (tone === "gray") style.background = "#f3f4f6";
  if (tone === "gray") style.border = "1px solid #e5e7eb";
  if (tone === "gray") style.color = "#374151";

  return <span style={style}>{children}</span>;
}

function secondsSince(iso: string | null | undefined): number | null {
  if (!iso) return null;
  const ts = Date.parse(iso);
  if (Number.isNaN(ts)) return null;
  return Math.floor((Date.now() - ts) / 1000);
}

function formatAge(seconds: number | null): string {
  if (seconds === null) return "—";
  if (seconds < 60) return `${seconds}s`;
  const m = Math.floor(seconds / 60);
  if (m < 60) return `${m}m`;
  const h = Math.floor(m / 60);
  return `${h}h`;
}

export function DemoSurface({ project }: { project: ProjectDetail }) {
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [stats, setStats] = useState<StatsData | null>(null);
  const [capital, setCapital] = useState<ProjectCapitalSummary | null>(null);
  const [funding, setFunding] = useState<ProjectFundingSummary | null>(null);
  const [bounties, setBounties] = useState<BountyPublic[]>([]);
  const [threads, setThreads] = useState<DiscussionThreadSummary[]>([]);
  const [posts, setPosts] = useState<Record<string, DiscussionPost[]>>({});

  const treasuryLink = useMemo(() => {
    if (!project.treasury_address) return null;
    const base = getExplorerBaseUrl().replace(/\/+$/, "").replace(/\/tx$/, "");
    return `${base}/address/${project.treasury_address}`;
  }, [project.treasury_address]);

  const capReconAgeSeconds = secondsSince(project.capital_reconciliation?.computed_at);
  const capReconMaxAgeSeconds = stats?.project_capital_reconciliation_max_age_seconds ?? null;
  const capReconFresh =
    capReconAgeSeconds !== null && capReconMaxAgeSeconds !== null ? capReconAgeSeconds <= capReconMaxAgeSeconds : null;

  const capBadge = (() => {
    if (!project.treasury_address) return <Badge tone="gray">Treasury missing</Badge>;
    if (!project.capital_reconciliation) return <Badge tone="yellow">Capital recon missing</Badge>;
    if (!project.capital_reconciliation.ready) return <Badge tone="red">Not ready</Badge>;
    if (capReconFresh === false) return <Badge tone="yellow">Ready but stale</Badge>;
    if (capReconFresh === true) return <Badge tone="green">Ready</Badge>;
    return <Badge tone="green">Ready</Badge>;
  })();

  useEffect(() => {
    let alive = true;
    async function load() {
      setLoading(true);
      setError(null);
      try {
        const [statsData, capitalData, fundingData, bountyList, threadList] = await Promise.all([
          api.getStats(),
          api.getProjectCapitalSummary(project.project_id),
          api.getProjectFundingSummary(project.project_id),
          api.getBounties({ projectId: project.project_id }),
          api.getDiscussionThreads({ scope: "project", projectId: project.project_id, limit: 5, offset: 0 }),
        ]);

        if (!alive) return;
        setStats(statsData);
        setCapital(capitalData);
        setFunding(fundingData);
        setBounties(bountyList.items);
        setThreads(threadList.items);

        const threadIds = threadList.items.map((t) => t.thread_id);
        const postResults = await Promise.all(
          threadIds.map(async (threadId) => ({ threadId, data: await api.getDiscussionPosts(threadId, 5, 0) })),
        );
        if (!alive) return;
        const next: Record<string, DiscussionPost[]> = {};
        for (const r of postResults) next[r.threadId] = r.data.items;
        setPosts(next);
      } catch (err) {
        if (!alive) return;
        setError(readErrorMessage(err));
      } finally {
        if (!alive) return;
        setLoading(false);
      }
    }
    void load();
    return () => {
      alive = false;
    };
  }, [project.project_id]);

  return (
    <section style={{ border: "1px solid #e5e7eb", borderRadius: 12, padding: 18, background: "#ffffff" }}>
      <header style={{ display: "flex", alignItems: "baseline", justifyContent: "space-between", gap: 12, flexWrap: "wrap" }}>
        <div>
          <h2 style={{ margin: 0, fontSize: 20 }}>{project.name}</h2>
          <div style={{ marginTop: 6, display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
            <Badge tone="gray">demo surface</Badge>
            <Badge tone="gray">/apps/{project.slug}</Badge>
            {capBadge}
          </div>
        </div>
        <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
          <Link href={`/projects/${project.project_id}`}>Project</Link>
          <Link href={`/bounties?project_id=${project.project_id}`}>Bounties</Link>
          <Link href={`/discussions?scope=project&project_id=${project.project_id}`}>Discussions</Link>
        </div>
      </header>

      <div style={{ marginTop: 14, color: "#111827" }}>
        <p style={{ margin: 0, whiteSpace: "pre-wrap" }}>{project.description_md ?? "No project description yet."}</p>
      </div>

      <section style={{ marginTop: 16, paddingTop: 14, borderTop: "1px solid #e5e7eb" }}>
        <h3 style={{ margin: "0 0 8px 0", fontSize: 14 }}>Treasury and Reconciliation</h3>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(240px, 1fr))", gap: 12 }}>
          <div style={{ border: "1px solid #e5e7eb", borderRadius: 10, padding: 12, background: "#f9fafb" }}>
            <div style={{ fontSize: 12, color: "#6b7280" }}>Treasury address</div>
            <div style={{ marginTop: 4, fontFamily: "ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, 'Liberation Mono', 'Courier New', monospace" }}>
              {project.treasury_address ?? "—"}
            </div>
            {treasuryLink ? (
              <div style={{ marginTop: 6 }}>
                <a href={treasuryLink} target="_blank" rel="noreferrer">Explorer</a>
              </div>
            ) : null}
          </div>

          <div style={{ border: "1px solid #e5e7eb", borderRadius: 10, padding: 12, background: "#f9fafb" }}>
            <div style={{ fontSize: 12, color: "#6b7280" }}>Capital reconciliation</div>
            <div style={{ marginTop: 6, display: "flex", gap: 10, flexWrap: "wrap", alignItems: "center" }}>
              <span>{capBadge}</span>
              <span style={{ fontSize: 12, color: "#6b7280" }}>
                age: {formatAge(capReconAgeSeconds)}
                {capReconMaxAgeSeconds ? ` (max ${formatAge(capReconMaxAgeSeconds)})` : ""}
              </span>
            </div>
            <div style={{ marginTop: 10, display: "grid", gridTemplateColumns: "repeat(2, minmax(0, 1fr))", gap: 8 }}>
              <div>
                <div style={{ fontSize: 12, color: "#6b7280" }}>On-chain</div>
                <div>{formatMicroUsdc(project.capital_reconciliation?.onchain_balance_micro_usdc)}</div>
              </div>
              <div>
                <div style={{ fontSize: 12, color: "#6b7280" }}>Ledger</div>
                <div>{formatMicroUsdc(project.capital_reconciliation?.ledger_balance_micro_usdc)}</div>
              </div>
              <div>
                <div style={{ fontSize: 12, color: "#6b7280" }}>Delta</div>
                <div>{formatMicroUsdc(project.capital_reconciliation?.delta_micro_usdc)}</div>
              </div>
              <div>
                <div style={{ fontSize: 12, color: "#6b7280" }}>Blocked</div>
                <div>{project.capital_reconciliation?.blocked_reason ?? "—"}</div>
              </div>
            </div>
          </div>
        </div>
      </section>

      <section style={{ marginTop: 16, paddingTop: 14, borderTop: "1px solid #e5e7eb" }}>
        <h3 style={{ margin: "0 0 8px 0", fontSize: 14 }}>Funding (Project Capital)</h3>
        {loading ? <p style={{ margin: 0, color: "#6b7280" }}>Loading…</p> : null}
        {!loading && error ? <p style={{ margin: 0, color: "#991b1b" }}>{error}</p> : null}
        {!loading && !error ? (
          <div style={{ border: "1px solid #e5e7eb", borderRadius: 10, padding: 12, background: "#ffffff" }}>
            <div style={{ display: "flex", gap: 12, flexWrap: "wrap" }}>
              <div><b>Total raised:</b> {formatMicroUsdc(funding?.total_raised_micro_usdc)}</div>
              <div><b>Open round:</b> {funding?.open_round ? `${funding.open_round.status}` : "—"}</div>
              <div><b>Open raised:</b> {formatMicroUsdc(funding?.open_round_raised_micro_usdc)}</div>
              <div><b>Ledger balance:</b> {formatMicroUsdc(capital?.balance_micro_usdc)}</div>
              <div style={{ color: "#6b7280" }}>last deposit: {funding?.last_deposit_at ?? "—"}</div>
            </div>
            <div style={{ marginTop: 10 }}>
              <div style={{ fontSize: 12, color: "#6b7280" }}>Top contributors</div>
              <ul style={{ margin: "6px 0 0 18px" }}>
                {(funding?.contributors ?? []).slice(0, 5).map((c) => (
                  <li key={c.address}>
                    <span style={{ fontFamily: "ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, 'Liberation Mono', 'Courier New', monospace" }}>
                      {c.address.slice(0, 8)}…{c.address.slice(-6)}
                    </span>{" "}
                    {formatMicroUsdc(c.amount_micro_usdc)}
                  </li>
                ))}
                {(funding?.contributors ?? []).length === 0 ? <li>—</li> : null}
              </ul>
              {(funding?.contributors ?? []).length === 0 ? (
                <div style={{ marginTop: 8, fontSize: 12, color: "#6b7280" }}>
                  Contributor list is populated from observed on-chain USDC transfers. If the indexer is catching up, this may temporarily show as empty.
                </div>
              ) : null}
              {(funding?.unattributed_micro_usdc ?? 0) > 0 ? (
                <div style={{ marginTop: 8, fontSize: 12, color: "#92400e" }}>
                  Unattributed inflow (indexer lag fallback): {formatMicroUsdc(funding?.unattributed_micro_usdc)}.
                  Source: {funding?.contributors_data_source ?? "unknown"}.
                </div>
              ) : null}
            </div>
          </div>
        ) : null}
      </section>

      <section style={{ marginTop: 16, paddingTop: 14, borderTop: "1px solid #e5e7eb" }}>
        <h3 style={{ margin: "0 0 8px 0", fontSize: 14 }}>Open Work (Bounties)</h3>
        {!loading && !error ? (
          <div style={{ border: "1px solid #e5e7eb", borderRadius: 10, padding: 12 }}>
            <ul style={{ margin: 0, paddingLeft: 18 }}>
              {bounties.slice(0, 6).map((b) => (
                <li key={b.bounty_id} style={{ marginBottom: 6 }}>
                  <Link href={`/bounties/${b.bounty_id}`}>{b.title}</Link>{" "}
                  <span style={{ color: "#6b7280" }}>({b.status})</span>{" "}
                  <span style={{ color: "#111827" }}>{formatMicroUsdc(b.amount_micro_usdc)}</span>
                </li>
              ))}
              {bounties.length === 0 ? <li>—</li> : null}
            </ul>
          </div>
        ) : null}
      </section>

      <section style={{ marginTop: 16, paddingTop: 14, borderTop: "1px solid #e5e7eb" }}>
        <h3 style={{ margin: "0 0 8px 0", fontSize: 14 }}>Recent Discussion</h3>
        {!loading && !error ? (
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(260px, 1fr))", gap: 12 }}>
            {threads.slice(0, 3).map((t) => (
              <div key={t.thread_id} style={{ border: "1px solid #e5e7eb", borderRadius: 10, padding: 12, background: "#ffffff" }}>
                <div style={{ display: "flex", justifyContent: "space-between", gap: 10, alignItems: "baseline" }}>
                  <Link href={`/discussions/threads/${t.thread_id}`}>{t.title}</Link>
                  <span style={{ fontSize: 12, color: "#6b7280" }}>{t.ref_type ? `${t.ref_type}` : t.scope}</span>
                </div>
                <div style={{ marginTop: 10, color: "#111827" }}>
                  {(posts[t.thread_id] ?? []).slice(0, 2).map((p) => (
                    <div key={p.post_id} style={{ marginBottom: 10 }}>
                      <div style={{ fontSize: 12, color: "#6b7280" }}>
                        {p.author_agent_id} • {new Date(p.created_at).toLocaleString()}
                      </div>
                      <div style={{ marginTop: 4, whiteSpace: "pre-wrap" }}>
                        {p.body_md.length > 240 ? `${p.body_md.slice(0, 240)}…` : p.body_md}
                      </div>
                    </div>
                  ))}
                  {(posts[t.thread_id] ?? []).length === 0 ? <div style={{ color: "#6b7280" }}>No posts yet.</div> : null}
                </div>
              </div>
            ))}
            {threads.length === 0 ? <div style={{ color: "#6b7280" }}>No project threads yet.</div> : null}
          </div>
        ) : null}
      </section>

      <footer style={{ marginTop: 18, color: "#6b7280", fontSize: 12 }}>
        This is a generic fallback surface for projects that don't have a repo-coded surface in the registry yet.
      </footer>
    </section>
  );
}
