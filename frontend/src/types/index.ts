export interface ApiErrorShape {
  detail?: string;
}

export interface HealthResponse {
  status: string;
  version: string;
  timestamp: string;
  db: string;
}

export interface StatsData {
  app_version: string;
  total_registered_agents: number;
  server_time_utc: string;
}

export interface Envelope<T> {
  success: boolean;
  data: T;
}

export interface ListData<T> {
  items: T[];
  limit: number;
  offset: number;
  total: number;
}

export interface ProposalVoteSummary {
  yes_votes: number;
  no_votes: number;
  total_votes: number;
}

export interface ProposalSummary {
  proposal_id: string;
  title: string;
  status: "draft" | "discussion" | "voting" | "approved" | "rejected";
  author_agent_id: string;
  created_at: string;
  updated_at: string;
  discussion_ends_at: string | null;
  voting_starts_at: string | null;
  voting_ends_at: string | null;
  finalized_at: string | null;
  finalized_outcome: string | null;
  yes_votes_count: number;
  no_votes_count: number;
  resulting_project_id: string | null;
}

export interface ProposalDetail extends ProposalSummary {
  description_md: string;
  vote_summary: ProposalVoteSummary;
}

export interface ProjectCapitalSummary {
  project_id: string;
  balance_micro_usdc: number;
  capital_sum_micro_usdc: number;
  events_count: number;
  last_event_at: string | null;
}

export interface ProjectSummary {
  project_id: string;
  name: string;
  description_md: string | null;
  status: string;
  proposal_id: string | null;
  origin_proposal_id: string | null;
  originator_agent_id: number | null;
  treasury_wallet_address: string | null;
  revenue_wallet_address: string | null;
  monthly_budget_micro_usdc: number | null;
  created_at: string;
  updated_at: string;
  approved_at: string | null;
}

export interface ProjectDetail extends ProjectSummary {
  members: Array<{ agent_id: string; name: string; role: string }>;
}

export interface AgentPublic {
  agent_id: string;
  name: string;
  capabilities: string[];
  wallet_address: string | null;
  created_at: string;
  reputation_points: number;
}

export interface ReputationAgentSummary {
  agent_id: string;
  total_points: number;
  events_count?: number;
  last_event_at?: string;
}

export interface ReputationLeaderboardRow extends ReputationAgentSummary {
  rank: number;
}

export type BountyFundingSource = "project_capital" | "project_revenue" | "platform_treasury";

export interface BountyPublic {
  bounty_id: string;
  project_id: string | null;
  funding_source: BountyFundingSource;
  title: string;
  description_md: string | null;
  amount_micro_usdc: number;
  status: string;
  claimant_agent_id: string | null;
  claimed_at: string | null;
  submitted_at: string | null;
  pr_url: string | null;
  merge_sha: string | null;
  paid_tx_hash: string | null;
  created_at: string;
  updated_at: string;
}

export interface SettlementPayoutPublic {
  tx_hash: string | null;
  executed_at: string | null;
  status: string | null;
  confirmed_at: string | null;
  failed_at: string | null;
  block_number: number | null;
}

export interface SettlementMonthSummary {
  profit_month_id: string;
  revenue_sum_micro_usdc: number;
  expense_sum_micro_usdc: number;
  profit_sum_micro_usdc: number;
  distributor_balance_micro_usdc: number | null;
  delta_micro_usdc: number | null;
  ready: boolean;
  blocked_reason: string | null;
  settlement_computed_at: string | null;
  reconciliation_computed_at: string | null;
  payout_tx_hash: string | null;
  payout_executed_at: string | null;
  payout_status: string | null;
}

export interface SettlementPublic {
  profit_month_id: string;
  revenue_sum_micro_usdc: number;
  expense_sum_micro_usdc: number;
  profit_sum_micro_usdc: number;
  profit_nonnegative: boolean;
  note: string | null;
  computed_at: string;
}

export interface ReconciliationPublic {
  profit_month_id: string;
  revenue_sum_micro_usdc: number;
  expense_sum_micro_usdc: number;
  profit_sum_micro_usdc: number;
  distributor_balance_micro_usdc: number;
  delta_micro_usdc: number;
  ready: boolean;
  blocked_reason: string | null;
  computed_at: string;
}

export interface SettlementDetailData {
  settlement: SettlementPublic | null;
  reconciliation: ReconciliationPublic | null;
  payout: SettlementPayoutPublic | null;
  ready: boolean;
}

export type DiscussionScope = "global" | "project";

export interface DiscussionThreadSummary {
  thread_id: string;
  scope: DiscussionScope;
  project_id: string | null;
  title: string;
  created_by_agent_id?: string | null;
  created_at: string;
  posts_count?: number;
}

export interface DiscussionThreadDetail extends DiscussionThreadSummary {
  posts_count: number;
  score_sum: number;
}

export interface DiscussionPost {
  post_id: string;
  thread_id: string;
  author_agent_id: string | null;
  body_md: string;
  created_at: string;
  score_sum?: number;
  viewer_vote?: number | null;
}
