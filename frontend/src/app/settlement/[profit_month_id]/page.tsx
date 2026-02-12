"use client";

import { useCallback, useEffect, useState } from "react";

import { DataCard, PageContainer } from "@/components/Cards";
import { Loading } from "@/components/State";
import { ErrorState } from "@/components/ErrorState";
import { api, readErrorMessage } from "@/lib/api";
import { getExplorerTxUrl } from "@/lib/env";
import { formatBoolean, formatMicroUsdc } from "@/lib/format";
import type { SettlementDetailData } from "@/types";

function shortenHash(txHash: string): string {
  if (txHash.length <= 14) {
    return txHash;
  }
  return `${txHash.slice(0, 8)}...${txHash.slice(-6)}`;
}

export default function SettlementMonthDetailPage({ params }: { params: { profit_month_id: string } }) {
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [detail, setDetail] = useState<SettlementDetailData | null>(null);
  const [copyFeedback, setCopyFeedback] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const result = await api.getSettlementDetail(params.profit_month_id);
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

  const payoutTxHash = detail?.payout_tx_hash ?? detail?.payout?.tx_hash ?? null;
  const hasPayout = Boolean(payoutTxHash);
  const isReady = detail?.ready === true;

  const handleCopyTxHash = useCallback(async () => {
    if (!payoutTxHash) {
      return;
    }

    if (!navigator.clipboard?.writeText) {
      setCopyFeedback("Clipboard unavailable");
      return;
    }

    try {
      await navigator.clipboard.writeText(payoutTxHash);
      setCopyFeedback("Copied");
      window.setTimeout(() => {
        setCopyFeedback(null);
      }, 1500);
    } catch {
      setCopyFeedback("Copy failed");
    }
  }, [payoutTxHash]);

  return (
    <PageContainer title={`Settlement ${params.profit_month_id}`}>
      {loading ? <Loading message="Loading settlement detail..." /> : null}
      {!loading && error ? <ErrorState message={error} onRetry={load} /> : null}
      {!loading && !error && detail ? (
        <>
          <DataCard title="Settlement">
            {detail.settlement ? (
              <ul>
                <li>revenue_sum: {formatMicroUsdc(detail.settlement.revenue_sum_micro_usdc)}</li>
                <li>expense_sum: {formatMicroUsdc(detail.settlement.expense_sum_micro_usdc)}</li>
                <li>profit_sum: {formatMicroUsdc(detail.settlement.profit_sum_micro_usdc)}</li>
                <li>profit_nonnegative: {formatBoolean(detail.settlement.profit_nonnegative)}</li>
              </ul>
            ) : (
              <p>Settlement unavailable.</p>
            )}
          </DataCard>
          <DataCard title="Reconciliation">
            {detail.reconciliation ? (
              <ul>
                <li>
                  distributor_balance: {formatMicroUsdc(detail.reconciliation.distributor_balance_micro_usdc)}
                </li>
                <li>delta: {formatMicroUsdc(detail.reconciliation.delta_micro_usdc)}</li>
                <li>ready: {formatBoolean(detail.reconciliation.ready)}</li>
                <li>blocked_reason: {detail.reconciliation.blocked_reason}</li>
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
                  <button type="button" onClick={() => void handleCopyTxHash()}>
                    Copy
                  </button>
                  {copyFeedback ? <span> ({copyFeedback})</span> : null}
                </li>
                <li>executed_at: {detail.payout?.executed_at ?? "—"}</li>
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
            <p>ready: {formatBoolean(detail.ready)}</p>
            <p>
              status:{" "}
              {isReady && hasPayout ? (
                <span>Finalized ✅</span>
              ) : null}
              {isReady && !hasPayout ? <span>Ready (not paid)</span> : null}
              {!isReady && hasPayout ? <span>Paid (check ready)</span> : null}
              {!isReady && !hasPayout ? <span>Pending</span> : null}
            </p>
          </DataCard>
        </>
      ) : null}
    </PageContainer>
  );
}
