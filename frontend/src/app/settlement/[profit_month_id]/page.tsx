"use client";

import { useCallback, useEffect, useState } from "react";

import { DataCard, PageContainer } from "@/components/Cards";
import { Loading } from "@/components/State";
import { ErrorState } from "@/components/ErrorState";
import { api, readErrorMessage } from "@/lib/api";
import { formatBoolean, formatMicroUsdc } from "@/lib/format";
import type { SettlementDetailData } from "@/types";

export default function SettlementMonthDetailPage({ params }: { params: { profit_month_id: string } }) {
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [detail, setDetail] = useState<SettlementDetailData | null>(null);

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
          <DataCard title="Month status">
            <p>ready: {formatBoolean(detail.ready)}</p>
          </DataCard>
        </>
      ) : null}
    </PageContainer>
  );
}
