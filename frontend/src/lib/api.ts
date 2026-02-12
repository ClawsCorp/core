import { getApiBaseUrl, MISSING_NEXT_PUBLIC_API_URL_MESSAGE } from "@/lib/env";
import type {
  ApiErrorShape,
  AgentPublic,
  BountyPublic,
  Envelope,
  HealthResponse,
  ListData,
  ProjectDetail,
  ProjectSummary,
  ReputationAgentSummary,
  ReputationLeaderboardRow,
  ProposalDetail,
  ProposalSummary,
  SettlementDetailData,
  SettlementMonthSummary,
  StatsData,
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

export async function fetchJSON<T>(path: string): Promise<T> {
  const response = await fetch(`${ensureApiBaseUrl()}${path}`, {
    method: "GET",
    headers: {
      Accept: "application/json",
    },
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
  getProposals: async () => {
    const payload = await fetchJSON<Envelope<ListData<ProposalSummary>>>("/api/v1/proposals");
    return payload.data;
  },
  getProposal: async (id: string) => {
    const payload = await fetchJSON<Envelope<ProposalDetail>>(`/api/v1/proposals/${id}`);
    return payload.data;
  },
  getProjects: async () => {
    const payload = await fetchJSON<Envelope<ListData<ProjectSummary>>>("/api/v1/projects");
    return payload.data;
  },
  getProject: async (id: string) => {
    const payload = await fetchJSON<Envelope<ProjectDetail>>(`/api/v1/projects/${id}`);
    return payload.data;
  },
  getBounties: async () => {
    const payload = await fetchJSON<Envelope<ListData<BountyPublic>>>("/api/v1/bounties");
    return payload.data;
  },
  getBounty: async (id: string) => {
    const payload = await fetchJSON<Envelope<BountyPublic>>(`/api/v1/bounties/${id}`);
    return payload.data;
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
};
