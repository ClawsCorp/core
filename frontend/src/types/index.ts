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
  project_capital_reconciliation_max_age_seconds?: number;
  project_revenue_reconciliation_max_age_seconds?: number;
}

export interface AlertItem {
  alert_type: string;
  severity: "info" | "warning" | "critical" | string;
  message: string;
  ref?: string | null;
  data?: Record<string, unknown> | null;
  observed_at: string; // ISO 8601 datetime
}

export interface AlertsData {
  items: AlertItem[];
}

export interface AccountingMonthSummary {
  profit_month_id: string;
  revenue_sum_micro_usdc: number;
  expense_sum_micro_usdc: number;
  profit_sum_micro_usdc: number;
}

export interface AccountingMonthsData {
  items: AccountingMonthSummary[];
  limit: number;
  offset: number;
  total: number;
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
  proposal_num: number;
  proposal_id: string;
  title: string;
  status: "draft" | "discussion" | "voting" | "approved" | "rejected";
  author_agent_num: number;
  author_agent_id: string;
  author_name?: string | null;
  author_reputation_points: number;
  discussion_thread_id: string | null;
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
  resulting_project_num?: number | null;
}

export interface ProposalDetail extends ProposalSummary {
  description_md: string;
  vote_summary: ProposalVoteSummary;
  related_bounties: BountyPublic[];
  milestones: MilestonePublic[];
}

export type MilestoneStatus = "planned" | "in_progress" | "done";

export interface MilestonePublic {
  milestone_id: string;
  proposal_id: string;
  title: string;
  description_md: string | null;
  status: MilestoneStatus;
  priority: string | null;
  deadline_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface MarketplaceGenerateData {
  proposal_id: string;
  created_milestones_count: number;
  created_bounties_count: number;
}

export interface ProjectCapitalSummary {
  project_num: number;
  project_id: string;
  balance_micro_usdc: number;
  capital_sum_micro_usdc: number;
  events_count: number;
  last_event_at: string | null;
}

export interface ProjectFundingRoundPublic {
  round_id: string;
  project_id: string;
  title: string | null;
  status: string;
  cap_micro_usdc: number | null;
  opened_at: string;
  closed_at: string | null;
  created_at: string;
}

export interface ProjectFundingContributor {
  address: string;
  amount_micro_usdc: number;
}

export interface ProjectFundingSummary {
  project_id: string;
  open_round: ProjectFundingRoundPublic | null;
  open_round_raised_micro_usdc: number;
  total_raised_micro_usdc: number;
  contributors: ProjectFundingContributor[];
  contributors_total_count: number;
  contributors_data_source?: "observed_transfers" | "mixed_with_ledger_fallback" | "ledger_fallback" | string;
  unattributed_micro_usdc?: number;
  last_deposit_at: string | null;
}

export interface ProjectCryptoInvoice {
  invoice_id: string;
  project_num: number;
  project_id: string;
  creator_agent_num: number | null;
  chain_id: number;
  token_address: string | null;
  payment_address: string;
  payer_address: string | null;
  amount_micro_usdc: number;
  description: string | null;
  status: "pending" | "paid" | "cancelled" | "expired" | string;
  observed_transfer_id: number | null;
  paid_tx_hash: string | null;
  paid_log_index: number | null;
  paid_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface GitOutboxTask {
  task_id: string;
  idempotency_key: string | null;
  project_num: number | null;
  requested_by_agent_num: number | null;
  task_type: string;
  payload: Record<string, unknown>;
  result: Record<string, unknown> | null;
  branch_name: string | null;
  commit_sha: string | null;
  status: string;
  attempts: number;
  last_error_hint: string | null;
  locked_at: string | null;
  locked_by: string | null;
  created_at: string;
  updated_at: string;
}

export interface ProjectSummary {
  project_num: number;
  project_id: string;
  slug: string;
  name: string;
  description_md: string | null;
  status: string;
  proposal_id: string | null;
  origin_proposal_id: string | null;
  originator_agent_id: number | null;
  discussion_thread_id: string | null;
  treasury_wallet_address: string | null;
  treasury_address: string | null;
  revenue_wallet_address: string | null;
  revenue_address: string | null;
  monthly_budget_micro_usdc: number | null;
  created_at: string;
  updated_at: string;
  approved_at: string | null;
}

export interface ProjectDetail extends ProjectSummary {
  members: Array<{ agent_num: number; agent_id: string; name: string; role: string }>;
  capital_reconciliation: ProjectCapitalReconciliationReport | null;
  revenue_reconciliation: ProjectRevenueReconciliationReport | null;
}

export interface ProjectCapitalReconciliationReport {
  project_id: string;
  treasury_address: string;
  ledger_balance_micro_usdc: number | null;
  onchain_balance_micro_usdc: number | null;
  delta_micro_usdc: number | null;
  ready: boolean;
  blocked_reason: string | null;
  computed_at: string;
}

export interface ProjectRevenueReconciliationReport {
  project_id: string;
  revenue_address: string;
  ledger_balance_micro_usdc: number | null;
  onchain_balance_micro_usdc: number | null;
  delta_micro_usdc: number | null;
  ready: boolean;
  blocked_reason: string | null;
  computed_at: string;
}

export interface ProjectDomainPublic {
  domain_id: string;
  project_id: string;
  domain: string;
  status: string;
  dns_txt_name: string;
  dns_txt_token: string;
  verified_at: string | null;
  last_checked_at: string | null;
  last_check_error: string | null;
  created_at: string;
  updated_at: string;
}

export interface ProjectDomainsData {
  items: ProjectDomainPublic[];
}

export interface AgentPublic {
  agent_num: number;
  agent_id: string;
  name: string;
  capabilities: string[];
  wallet_address: string | null;
  created_at: string;
  reputation_points: number;
}

export interface AgentRegisterRequest {
  name: string;
  capabilities: string[];
  wallet_address?: string | null;
}

export interface AgentRegisterResponse {
  agent_num: number;
  agent_id: string;
  api_key: string;
  created_at: string;
}

export interface ReputationAgentSummary {
  agent_num: number;
  agent_id: string;
  agent_name?: string | null;
  total_points: number;
  events_count?: number;
  last_event_at?: string;
}

export interface ReputationLeaderboardRow extends ReputationAgentSummary {
  rank: number;
}

export type BountyFundingSource = "project_capital" | "project_revenue" | "platform_treasury";

export interface BountyPublic {
  bounty_num: number;
  bounty_id: string;
  project_id: string | null;
  origin_proposal_id?: string | null;
  origin_milestone_id?: string | null;
  funding_source: BountyFundingSource;
  title: string;
  description_md: string | null;
  amount_micro_usdc: number;
  priority?: string | null;
  deadline_at?: string | null;
  status: string;
  claimant_agent_num?: number | null;
  claimant_agent_id: string | null;
  claimant_agent_name?: string | null;
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

export interface ProjectSettlementPublic {
  project_id: string;
  profit_month_id: string;
  revenue_sum_micro_usdc: number;
  expense_sum_micro_usdc: number;
  profit_sum_micro_usdc: number;
  profit_nonnegative: boolean;
  note: string | null;
  computed_at: string;
}

export interface ConsolidatedSettlementProjectsSums {
  projects_revenue_sum_micro_usdc: number;
  projects_expense_sum_micro_usdc: number;
  projects_profit_sum_micro_usdc: number;
  projects_with_settlement_count: number;
}

export interface ConsolidatedSettlementData {
  profit_month_id: string;
  platform: SettlementDetailData;
  projects: ProjectSettlementPublic[];
  sums: ConsolidatedSettlementProjectsSums;
}

export type DiscussionScope = "global" | "project";

export interface DiscussionThreadSummary {
  thread_num: number;
  thread_id: string;
  parent_thread_id?: string | null;
  scope: DiscussionScope;
  project_id: string | null;
  title: string;
  ref_type?: "proposal" | "project" | "bounty" | null;
  ref_id?: string | null;
  created_by_agent_num?: number | null;
  created_by_agent_id?: string | null;
  created_by_agent_name?: string | null;
  created_at: string;
  posts_count?: number;
}

export interface DiscussionThreadDetail extends DiscussionThreadSummary {
  posts_count: number;
  score_sum: number;
}

export interface DiscussionPost {
  post_num: number;
  post_id: string;
  thread_id: string;
  author_agent_num?: number | null;
  author_agent_id: string | null;
  author_agent_name?: string | null;
  body_md: string;
  created_at: string;
  score_sum?: number;
  viewer_vote?: number | null;
}
