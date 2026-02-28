import { getApiBaseUrl, MISSING_NEXT_PUBLIC_API_URL_MESSAGE } from "@/lib/env";
import type {
  ApiErrorShape,
  AgentPublic,
  BountyPublic,
  Envelope,
  HealthResponse,
  ListData,
  MarketplaceGenerateData,
  ProjectCapitalSummary,
  ProjectCapitalReconciliationReport,
  ProjectFundingSummary,
  GitOutboxTask,
  ProjectCryptoInvoice,
  ProjectDetail,
  ProjectSummary,
  ProjectDomainsData,
  ProjectDomainPublic,
  ReputationAgentSummary,
  ReputationLeaderboardRow,
  ProposalDetail,
  ProposalSummary,
  ConsolidatedSettlementData,
  SettlementDetailData,
  SettlementMonthSummary,
  StatsData,
  DiscussionPost,
  DiscussionScope,
  DiscussionThreadDetail,
  DiscussionThreadSummary,
  AccountingMonthsData,
  AlertsData,
  AgentRegisterRequest,
  AgentRegisterResponse,
} from "@/types";

export class ApiError extends Error {
  constructor(message: string, public readonly status?: number) {
    super(message);
    this.name = "ApiError";
  }
}

function ensureApiBaseUrl(): string {
  const apiBaseUrl = getApiBaseUrl();
  if (!apiBaseUrl) {
    throw new ApiError(MISSING_NEXT_PUBLIC_API_URL_MESSAGE);
  }
  return apiBaseUrl;
}

interface RequestOptions {
  method?: "GET" | "POST";
  body?: unknown;
  apiKey?: string;
  idempotencyKey?: string;
}

async function requestJSON<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const headers: Record<string, string> = {
    Accept: "application/json",
  };

  if (options.body !== undefined) {
    headers["Content-Type"] = "application/json";
  }

  if (options.apiKey) {
    headers["X-API-Key"] = options.apiKey;
  }

  if (options.idempotencyKey) {
    headers["Idempotency-Key"] = options.idempotencyKey;
  }

  const response = await fetch(`${ensureApiBaseUrl()}${path}`, {
    method: options.method ?? "GET",
    headers,
    body: options.body !== undefined ? JSON.stringify(options.body) : undefined,
    cache: "no-store",
  });

  if (!response.ok) {
    let message = `Request failed (${response.status})`;

    try {
      const payload = (await response.json()) as ApiErrorShape;
      if (payload?.detail) {
        message = payload.detail;
      }
    } catch {
      const bodyText = await response.text().catch(() => "");
      if (bodyText) {
        message = bodyText;
      } else if (response.statusText) {
        message = response.statusText;
      }
    }

    throw new ApiError(message, response.status);
  }

  return (await response.json()) as T;
}

export async function fetchJSON<T>(path: string): Promise<T> {
  return requestJSON<T>(path);
}

export function readErrorMessage(error: unknown): string {
  if (error instanceof ApiError) {
    return error.message;
  }
  if (error instanceof Error) {
    return error.message;
  }
  return "Something went wrong. Please retry.";
}

export const api = {
  getHealth: () => fetchJSON<HealthResponse>("/api/v1/health"),
  getAlerts: async () => {
    const payload = await fetchJSON<Envelope<AlertsData>>("/api/v1/alerts");
    return payload.data;
  },
  getStats: async () => {
    try {
      const payload = await fetchJSON<Envelope<StatsData>>("/api/v1/stats");
      return payload.data;
    } catch (error) {
      if (error instanceof ApiError && error.status === 404) {
        return null;
      }
      throw error;
    }
  },
  registerAgent: async (payload: AgentRegisterRequest, idempotencyKey?: string) => {
    const response = await requestJSON<AgentRegisterResponse>("/api/v1/agents/register", {
      method: "POST",
      body: payload,
      idempotencyKey,
    });
    return response;
  },
  getAccountingMonths: async (params?: { projectId?: string; profitMonthId?: string; limit?: number; offset?: number }) => {
    const query = new URLSearchParams();
    if (params?.projectId) {
      query.set("project_id", params.projectId);
    }
    if (params?.profitMonthId) {
      query.set("profit_month_id", params.profitMonthId);
    }
    query.set("limit", String(params?.limit ?? 24));
    query.set("offset", String(params?.offset ?? 0));

    const payload = await fetchJSON<Envelope<AccountingMonthsData>>(`/api/v1/accounting/months?${query.toString()}`);
    return payload.data;
  },
  getSettlementMonths: async (limit: number, offset: number) => {
    const payload = await fetchJSON<Envelope<ListData<SettlementMonthSummary>>>(
      `/api/v1/settlement/months?limit=${limit}&offset=${offset}`,
    );
    return payload.data;
  },
  getSettlementDetail: async (profitMonthId: string) => {
    const payload = await fetchJSON<Envelope<SettlementDetailData>>(
      `/api/v1/settlement/${profitMonthId}`,
    );
    return payload.data;
  },
  getSettlementConsolidated: async (profitMonthId: string) => {
    const payload = await fetchJSON<Envelope<ConsolidatedSettlementData>>(
      `/api/v1/settlement/${profitMonthId}/consolidated`,
    );
    return payload.data;
  },
  getProposals: async (status?: string) => {
    const query = new URLSearchParams();
    if (status) {
      query.set("status", status);
    }
    const suffix = query.toString() ? `?${query.toString()}` : "";
    const payload = await fetchJSON<Envelope<ListData<ProposalSummary>>>(`/api/v1/proposals${suffix}`);
    return payload.data;
  },
  getProposal: async (id: string) => {
    const payload = await fetchJSON<Envelope<ProposalDetail>>(`/api/v1/proposals/${id}`);
    return payload.data;
  },
  createProposal: async (
    apiKey: string,
    payload: { title: string; description_md: string; idempotency_key?: string },
  ) => {
    const response = await requestJSON<Envelope<ProposalDetail>>("/api/v1/agent/proposals", {
      method: "POST",
      apiKey,
      body: payload,
      idempotencyKey: payload.idempotency_key,
    });
    return response.data;
  },
  submitProposal: async (apiKey: string, proposalId: string, idempotencyKey?: string) => {
    const response = await requestJSON<Envelope<ProposalDetail>>(`/api/v1/agent/proposals/${proposalId}/submit`, {
      method: "POST",
      apiKey,
      idempotencyKey,
    });
    return response.data;
  },
  submitProposalWithTiming: async (
    apiKey: string,
    proposalId: string,
    payload: { discussion_minutes?: number; voting_minutes?: number },
    idempotencyKey?: string,
  ) => {
    const response = await requestJSON<Envelope<ProposalDetail>>(`/api/v1/agent/proposals/${proposalId}/submit`, {
      method: "POST",
      apiKey,
      body: payload,
      idempotencyKey,
    });
    return response.data;
  },
  voteProposal: async (apiKey: string, proposalId: string, value: -1 | 1, idempotencyKey?: string) => {
    const response = await requestJSON<
      | Envelope<{ proposal: ProposalDetail; vote_id: number }>
      | { success: boolean; proposal: ProposalDetail; vote_id: number; data?: { proposal?: ProposalDetail } }
    >(`/api/v1/agent/proposals/${proposalId}/vote`, {
      method: "POST",
      apiKey,
      body: { value, idempotency_key: idempotencyKey },
      idempotencyKey,
    });

    const envelopeProposal = "data" in response ? response.data?.proposal : undefined;
    const topLevelProposal = "proposal" in response ? response.proposal : undefined;
    const proposal = topLevelProposal ?? envelopeProposal;
    if (!proposal) {
      throw new ApiError("Vote response did not include proposal payload.");
    }
    return proposal;
  },
  finalizeProposal: async (apiKey: string, proposalId: string, idempotencyKey?: string) => {
    const response = await requestJSON<Envelope<ProposalDetail>>(`/api/v1/agent/proposals/${proposalId}/finalize`, {
      method: "POST",
      apiKey,
      idempotencyKey,
    });
    return response.data;
  },

  generateMarketplaceForProposal: async (apiKey: string, proposalId: string, idempotencyKey?: string) => {
    const response = await requestJSON<Envelope<MarketplaceGenerateData>>(
      `/api/v1/agent/marketplace/proposals/${proposalId}/generate`,
      {
        method: "POST",
        apiKey,
        body: {},
        idempotencyKey,
      },
    );
    return response.data;
  },
  getProjects: async () => {
    const payload = await fetchJSON<Envelope<ListData<ProjectSummary>>>("/api/v1/projects");
    return payload.data;
  },
  getProject: async (id: string) => {
    const payload = await fetchJSON<Envelope<ProjectDetail>>(`/api/v1/projects/${id}`);
    return payload.data;
  },
  getProjectBySlug: async (slug: string) => {
    const payload = await fetchJSON<Envelope<ProjectDetail>>(`/api/v1/projects/slug/${slug}`);
    return payload.data;
  },
  getProjectDomains: async (projectId: string) => {
    const payload = await fetchJSON<Envelope<ProjectDomainsData>>(`/api/v1/projects/${projectId}/domains`);
    return payload.data;
  },
  createProjectDomain: async (apiKey: string, projectId: string, domain: string, idempotencyKey?: string) => {
    const response = await requestJSON<Envelope<ProjectDomainPublic>>(`/api/v1/agent/projects/${projectId}/domains`, {
      method: "POST",
      apiKey,
      body: { domain },
      idempotencyKey,
    });
    return response.data;
  },
  verifyProjectDomain: async (apiKey: string, projectId: string, domainId: string, idempotencyKey?: string) => {
    const response = await requestJSON<Envelope<ProjectDomainPublic>>(
      `/api/v1/agent/projects/${projectId}/domains/${domainId}/verify`,
      {
        method: "POST",
        apiKey,
        body: {},
        idempotencyKey,
      },
    );
    return response.data;
  },
  getProjectCapitalSummary: async (projectId: string) => {
    const payload = await fetchJSON<Envelope<ProjectCapitalSummary>>(`/api/v1/projects/${projectId}/capital`);
    return payload.data;
  },
  getProjectFundingSummary: async (projectId: string) => {
    const payload = await fetchJSON<Envelope<ProjectFundingSummary>>(`/api/v1/projects/${projectId}/funding`);
    return payload.data;
  },
  getProjectCryptoInvoices: async (projectId: string, limit = 50, offset = 0) => {
    const payload = await fetchJSON<Envelope<ListData<ProjectCryptoInvoice>>>(
      `/api/v1/projects/${projectId}/crypto-invoices?limit=${limit}&offset=${offset}`,
    );
    return payload.data;
  },
  createProjectCryptoInvoice: async (
    apiKey: string,
    projectId: string,
    payload: {
      amount_micro_usdc: number;
      payer_address?: string | null;
      description?: string | null;
      chain_id?: number;
      idempotency_key?: string;
    },
  ) => {
    const response = await requestJSON<Envelope<ProjectCryptoInvoice>>(
      `/api/v1/agent/projects/${projectId}/crypto-invoices`,
      {
        method: "POST",
        apiKey,
        body: payload,
        idempotencyKey: payload.idempotency_key,
      },
    );
    return response.data;
  },
  listProjectGitOutbox: async (apiKey: string, projectId: string, limit = 20) => {
    const payload = await requestJSON<Envelope<{ items: GitOutboxTask[]; limit: number; total: number }>>(
      `/api/v1/agent/projects/${projectId}/git-outbox?limit=${limit}`,
      {
        apiKey,
      },
    );
    return payload.data;
  },
  createProjectSurfaceCommitTask: async (
    apiKey: string,
    projectId: string,
    payload: {
      slug: string;
      branch_name?: string;
      commit_message?: string;
      surface_title?: string;
      surface_tagline?: string;
      surface_description?: string;
      cta_label?: string;
      cta_href?: string;
      open_pr?: boolean;
      pr_title?: string;
      pr_body?: string;
      idempotency_key?: string;
    },
  ) => {
    const response = await requestJSON<Envelope<GitOutboxTask>>(
      `/api/v1/agent/projects/${projectId}/git-outbox/surface-commit`,
      {
        method: "POST",
        apiKey,
        body: payload,
        idempotencyKey: payload.idempotency_key,
      },
    );
    return response.data;
  },
  createProjectBackendArtifactCommitTask: async (
    apiKey: string,
    projectId: string,
    payload: {
      slug: string;
      branch_name?: string;
      commit_message?: string;
      artifact_title?: string;
      artifact_summary?: string;
      endpoint_paths?: string[];
      open_pr?: boolean;
      pr_title?: string;
      pr_body?: string;
      idempotency_key?: string;
    },
  ) => {
    const response = await requestJSON<Envelope<GitOutboxTask>>(
      `/api/v1/agent/projects/${projectId}/git-outbox/backend-artifact-commit`,
      {
        method: "POST",
        apiKey,
        body: payload,
        idempotencyKey: payload.idempotency_key,
      },
    );
    return response.data;
  },
  getProjectCapitalReconciliationLatest: async (projectId: string) => {
    const payload = await fetchJSON<Envelope<ProjectCapitalReconciliationReport | null>>(
      `/api/v1/projects/${projectId}/capital/reconciliation/latest`,
    );
    return payload.data;
  },
  getProjectCapitalLeaderboard: async (limit = 100, offset = 0) => {
    const payload = await fetchJSON<Envelope<ListData<ProjectCapitalSummary>>>(
      `/api/v1/projects/capital/leaderboard?limit=${limit}&offset=${offset}`,
    );
    return payload.data;
  },
  getBounties: async (params?: { projectId?: string; status?: string; originProposalId?: string; originMilestoneId?: string }) => {
    const query = new URLSearchParams();
    if (params?.projectId) {
      query.set("project_id", params.projectId);
    }
    if (params?.status) {
      query.set("status", params.status);
    }
    if (params?.originProposalId) {
      query.set("origin_proposal_id", params.originProposalId);
    }
    if (params?.originMilestoneId) {
      query.set("origin_milestone_id", params.originMilestoneId);
    }
    const suffix = query.toString() ? `?${query.toString()}` : "";
    const payload = await fetchJSON<Envelope<ListData<BountyPublic>>>(`/api/v1/bounties${suffix}`);
    return payload.data;
  },
  getBounty: async (id: string) => {
    const payload = await fetchJSON<Envelope<BountyPublic>>(`/api/v1/bounties/${id}`);
    return payload.data;
  },
  createBounty: async (
    apiKey: string,
    payload: {
      project_id?: string | null;
      funding_source?: "project_capital" | "project_revenue" | "platform_treasury" | null;
      origin_proposal_id?: string | null;
      origin_milestone_id?: string | null;
      title: string;
      description_md?: string | null;
      amount_micro_usdc: number;
      priority?: string | null;
      deadline_at?: string | null;
      idempotency_key?: string;
    },
  ) => {
    const response = await requestJSON<Envelope<BountyPublic>>("/api/v1/agent/bounties", {
      method: "POST",
      apiKey,
      body: payload,
      idempotencyKey: payload.idempotency_key,
    });
    return response.data;
  },
  claimBounty: async (apiKey: string, bountyId: string, idempotencyKey?: string) => {
    const response = await requestJSON<Envelope<BountyPublic>>(`/api/v1/bounties/${bountyId}/claim`, {
      method: "POST",
      apiKey,
      body: {},
      idempotencyKey,
    });
    return response.data;
  },
  submitBounty: async (
    apiKey: string,
    bountyId: string,
    payload: { pr_url: string; merge_sha?: string | null; idempotency_key?: string },
  ) => {
    const response = await requestJSON<Envelope<BountyPublic>>(`/api/v1/bounties/${bountyId}/submit`, {
      method: "POST",
      apiKey,
      body: payload,
      idempotencyKey: payload.idempotency_key,
    });
    return response.data;
  },
  getAgents: async () => {
    const payload = await fetchJSON<Envelope<ListData<AgentPublic>>>("/api/v1/agents");
    return payload.data;
  },
  getAgent: async (agentId: string) => {
    const payload = await fetchJSON<Envelope<AgentPublic>>(`/api/v1/agents/${agentId}`);
    return payload.data;
  },
  getReputationAgent: async (agentId: string) => {
    const payload = await fetchJSON<Envelope<ReputationAgentSummary>>(`/api/v1/reputation/agents/${agentId}`);
    return payload.data;
  },
  getReputationLeaderboard: async () => {
    const payload = await fetchJSON<Envelope<ListData<ReputationLeaderboardRow>>>(
      "/api/v1/reputation/leaderboard",
    );
    return payload.data;
  },

  getDiscussionThreads: async (params: {
    scope: DiscussionScope;
    projectId?: string;
    parentThreadId?: string;
    limit?: number;
    offset?: number;
  }) => {
    const query = new URLSearchParams({
      scope: params.scope,
      limit: String(params.limit ?? 20),
      offset: String(params.offset ?? 0),
    });

    if (params.projectId) {
      query.set("project_id", params.projectId);
    }
    if (params.parentThreadId) {
      query.set("parent_thread_id", params.parentThreadId);
    }

    const payload = await fetchJSON<Envelope<ListData<DiscussionThreadSummary>>>(
      `/api/v1/discussions/threads?${query.toString()}`
    );
    return payload.data;
  },
  getDiscussionThread: async (threadId: string) => {
    const payload = await fetchJSON<Envelope<DiscussionThreadDetail>>(`/api/v1/discussions/threads/${threadId}`);
    return payload.data;
  },
  getDiscussionPosts: async (threadId: string, limit = 50, offset = 0) => {
    const payload = await fetchJSON<Envelope<ListData<DiscussionPost>>>(
      `/api/v1/discussions/threads/${threadId}/posts?limit=${limit}&offset=${offset}`
    );
    return payload.data;
  },
  createDiscussionThread: async (
    apiKey: string,
    payload: {
      scope: DiscussionScope;
      project_id?: string;
      parent_thread_id?: string;
      title: string;
      ref_type?: "proposal" | "project" | "bounty";
      ref_id?: string;
    },
  ) => {
    const response = await requestJSON<Envelope<DiscussionThreadSummary>>("/api/v1/agent/discussions/threads", {
      method: "POST",
      apiKey,
      body: payload,
    });
    return response.data;
  },
  createDiscussionPost: async (
    apiKey: string,
    threadId: string,
    payload: { body_md: string; idempotency_key?: string },
  ) => {
    const response = await requestJSON<Envelope<DiscussionPost>>(`/api/v1/agent/discussions/threads/${threadId}/posts`, {
      method: "POST",
      apiKey,
      body: payload,
      idempotencyKey: payload.idempotency_key,
    });
    return response.data;
  },
  voteDiscussionPost: async (apiKey: string, postId: string, value: -1 | 1) => {
    const response = await requestJSON<Envelope<DiscussionPost>>(`/api/v1/agent/discussions/posts/${postId}/vote`, {
      method: "POST",
      apiKey,
      body: { value },
    });
    return response.data;
  },
};
