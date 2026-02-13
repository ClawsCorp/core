"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import { DataCard, PageContainer } from "@/components/Cards";
import { EmptyState, Loading } from "@/components/State";
import { ErrorState } from "@/components/ErrorState";
import { api, readErrorMessage } from "@/lib/api";
import { getExplorerTxUrl } from "@/lib/env";
import { formatBoolean, formatMicroUsdc } from "@/lib/format";
import type { SettlementMonthSummary } from "@/types";

export default function SettlementPage() {
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [items, setItems] = useState<SettlementMonthSummary[]>([]);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const result = await api.getSettlementMonths(24, 0);
      setItems(result.items);
    } catch (err) {
      setError(readErrorMessage(err));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  return (
    <PageContainer title="Settlement Months">
      {loading ? <Loading message="Loading settlement months..." /> : null}
      {!loading && error ? <ErrorState message={error} onRetry={load} /> : null}
      {!loading && !error && items.length === 0 ? <EmptyState message="No settlement months found." /> : null}
      {!loading && !error && items.length > 0
        ? items.map((month) => {
            const payoutTxHash = month.payout_tx_hash;
            const hasPayout = Boolean(payoutTxHash);
            const payoutStatus = month.payout_status;
            const monthFinalized = month.ready && payoutStatus === "confirmed";

            return (
              <DataCard key={month.profit_month_id} title={month.profit_month_id}>
                <p>revenue_sum: {formatMicroUsdc(month.revenue_sum_micro_usdc)}</p>
                <p>expense_sum: {formatMicroUsdc(month.expense_sum_micro_usdc)}</p>
                <p>profit_sum: {formatMicroUsdc(month.profit_sum_micro_usdc)}</p>
                <p>distributor_balance: {formatMicroUsdc(month.distributor_balance_micro_usdc)}</p>
                <p>delta: {formatMicroUsdc(month.delta_micro_usdc)}</p>
                <p>ready: {formatBoolean(month.ready)}</p>
                <p>payout: {monthFinalized ? "Finalized ✅" : payoutStatus === "failed" ? "Failed" : hasPayout ? "Pending" : "Not paid"}</p>
                {payoutTxHash ? (
                  <p>
                    explorer: <a href={getExplorerTxUrl(payoutTxHash)} target="_blank" rel="noreferrer">View tx</a>
                  </p>
                ) : null}
                <Link href={`/settlement/${month.profit_month_id}`}>Open month detail</Link>
              </DataCard>
            );
          })
        : null}
    </PageContainer>
  );
}
