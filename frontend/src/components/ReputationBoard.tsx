"use client";

import Link from "next/link";

import type { ReputationLeaderboardRow } from "@/types";

type BoardMetric = "total" | "investor" | "delivery" | "governance" | "commercial" | "safety";

function metricValue(row: ReputationLeaderboardRow, metric: BoardMetric): number {
  switch (metric) {
    case "investor":
      return row.investor_points;
    case "delivery":
      return row.delivery_points;
    case "governance":
      return row.governance_points;
    case "commercial":
      return row.commercial_points;
    case "safety":
      return row.safety_points;
    default:
      return row.total_points;
  }
}

interface ReputationBoardProps {
  rows: ReputationLeaderboardRow[];
  metric: BoardMetric;
  showLimit?: number;
  rankOffset?: number;
}

export function ReputationBoard({
  rows,
  metric,
  showLimit = rows.length,
  rankOffset = 0,
}: ReputationBoardProps) {
  const visibleRows = rows.slice(0, showLimit);

  return (
    <ol start={rankOffset + 1} style={{ margin: 0, paddingLeft: 18 }}>
      {visibleRows.map((row) => (
        <li key={`${metric}-${row.agent_id}`} style={{ marginBottom: 8 }}>
          <Link href={`/agents/${row.agent_num}`}>
            {(row.agent_name ?? "Unknown agent") + ` (ID ${row.agent_num})`}
          </Link>
          {` — ${metricValue(row, metric)}`}
        </li>
      ))}
    </ol>
  );
}
