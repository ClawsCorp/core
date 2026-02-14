"use client";

import { useCallback, useEffect, useState } from "react";

import { DataCard, PageContainer } from "@/components/Cards";
import { CopyButton } from "@/components/CopyButton";
import { Loading } from "@/components/State";
import { ErrorState } from "@/components/ErrorState";
import { api, readErrorMessage } from "@/lib/api";
import { getExplorerTxUrl } from "@/lib/env";
import { formatBoolean, formatMicroUsdc } from "@/lib/format";
import type { ConsolidatedSettlementData } from "@/types";

function shortenHash(txHash: string): string {
  if (txHash.length <= 14) {
    return txHash;
  }
  return `${txHash.slice(0, 8)}...${txHash.slice(-6)}`;
}

export default function SettlementMonthDetailPage({ params }: { params: { profit_month_id: string } }) {
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [detail, setDetail] = useState<ConsolidatedSettlementData | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const result = await api.getSettlementConsolidated(params.profit_month_id);
      setDetail(result);
    } catch (err) {
      setError(readErrorMessage(err));
    } finally {
      setLoading(false);
    }
  }, [params.profit_month_id]);

  useEffect(() => {
    void load();
  }, [load]);

  const platform = detail?.platform ?? null;
  const payoutTxHash = platform?.payout?.tx_hash ?? null;
  const payoutStatus = platform?.payout?.status ?? null;
  const hasPayout = Boolean(payoutTxHash);
  const isReady = platform?.ready === true;
  const isFinalized = isReady && payoutStatus === "confirmed";

  return (
    <PageContainer title={`Settlement ${params.profit_month_id}`}>
      {loading ? <Loading message="Loading settlement detail..." /> : null}
      {!loading && error ? <ErrorState message={error} onRetry={load} /> : null}
      {!loading && !error && detail ? (
        <>
          <DataCard title="Settlement">
            {platform?.settlement ? (
              <ul>
                <li>revenue_sum: {formatMicroUsdc(platform.settlement.revenue_sum_micro_usdc)}</li>
                <li>expense_sum: {formatMicroUsdc(platform.settlement.expense_sum_micro_usdc)}</li>
                <li>profit_sum: {formatMicroUsdc(platform.settlement.profit_sum_micro_usdc)}</li>
                <li>profit_nonnegative: {formatBoolean(platform.settlement.profit_nonnegative)}</li>
              </ul>
            ) : (
              <p>Settlement unavailable.</p>
            )}
          </DataCard>
          <DataCard title="Reconciliation">
            {platform?.reconciliation ? (
              <ul>
                <li>
                  distributor_balance: {formatMicroUsdc(platform.reconciliation.distributor_balance_micro_usdc)}
                </li>
                <li>delta: {formatMicroUsdc(platform.reconciliation.delta_micro_usdc)}</li>
                <li>ready: {formatBoolean(platform.reconciliation.ready)}</li>
                <li>blocked_reason: {platform.reconciliation.blocked_reason}</li>
              </ul>
            ) : (
              <p>Reconciliation unavailable.</p>
            )}
          </DataCard>
          <DataCard title="Payout">
            {hasPayout ? (
              <ul>
                <li>
                  tx_hash: {shortenHash(payoutTxHash ?? "")}{" "}
                  {payoutTxHash ? <CopyButton value={payoutTxHash} /> : null}
                </li>
                <li>executed_at: {platform?.payout?.executed_at ?? "—"}</li>
                <li>status: {payoutStatus ?? "—"}</li>
                <li>confirmed_at: {platform?.payout?.confirmed_at ?? "—"}</li>
                <li>failed_at: {platform?.payout?.failed_at ?? "—"}</li>
                <li>block_number: {platform?.payout?.block_number ?? "—"}</li>
                <li>
                  explorer:{" "}
                  <a
                    href={getExplorerTxUrl(payoutTxHash ?? "")}
                    target="_blank"
                    rel="noreferrer"
                  >
                    View tx
                  </a>
                </li>
              </ul>
            ) : (
              <p>No payout executed yet</p>
            )}
          </DataCard>
          <DataCard title="Month status">
            <p>ready: {formatBoolean(platform?.ready ?? false)}</p>
            <p>
              status:{" "}
              {isFinalized ? <span>Finalized ✅</span> : null}
              {!isFinalized && payoutStatus === "failed" ? <span>Failed</span> : null}
              {!isFinalized && payoutStatus !== "failed" && hasPayout ? <span>Pending</span> : null}
              {!isFinalized && !hasPayout && isReady ? <span>Ready (not paid)</span> : null}
              {!isFinalized && !hasPayout && !isReady ? <span>Pending</span> : null}
            </p>
          </DataCard>

          <DataCard title="Projects (consolidated)">
            <ul>
              <li>projects_with_settlement: {detail.sums.projects_with_settlement_count}</li>
              <li>projects_revenue_sum: {formatMicroUsdc(detail.sums.projects_revenue_sum_micro_usdc)}</li>
              <li>projects_expense_sum: {formatMicroUsdc(detail.sums.projects_expense_sum_micro_usdc)}</li>
              <li>projects_profit_sum: {formatMicroUsdc(detail.sums.projects_profit_sum_micro_usdc)}</li>
            </ul>

            {detail.projects.length === 0 ? (
              <p>No project settlement rows for this month yet.</p>
            ) : (
              <div style={{ overflowX: "auto" }}>
                <table style={{ width: "100%", borderCollapse: "collapse" }}>
                  <thead>
                    <tr>
                      <th style={{ textAlign: "left", padding: "8px 6px" }}>project_id</th>
                      <th style={{ textAlign: "right", padding: "8px 6px" }}>revenue</th>
                      <th style={{ textAlign: "right", padding: "8px 6px" }}>expense</th>
                      <th style={{ textAlign: "right", padding: "8px 6px" }}>profit</th>
                      <th style={{ textAlign: "left", padding: "8px 6px" }}>computed_at</th>
                    </tr>
                  </thead>
                  <tbody>
                    {detail.projects.map((p) => (
                      <tr key={`${p.project_id}:${p.computed_at}`}>
                        <td style={{ padding: "8px 6px" }}>{p.project_id}</td>
                        <td style={{ padding: "8px 6px", textAlign: "right" }}>{formatMicroUsdc(p.revenue_sum_micro_usdc)}</td>
                        <td style={{ padding: "8px 6px", textAlign: "right" }}>{formatMicroUsdc(p.expense_sum_micro_usdc)}</td>
                        <td style={{ padding: "8px 6px", textAlign: "right" }}>{formatMicroUsdc(p.profit_sum_micro_usdc)}</td>
                        <td style={{ padding: "8px 6px" }}>{p.computed_at}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </DataCard>
        </>
      ) : null}
    </PageContainer>
  );
}
