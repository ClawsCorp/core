import { MISSING_API_BASE_URL_MESSAGE, getApiBaseUrl } from "@/lib/constants";
import type {
  ApiErrorShape,
  BountyPublic,
  Envelope,
  HealthResponse,
  ListData,
  ProjectDetail,
  ProjectSummary,
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

const API_BASE = getApiBaseUrl();

function ensureApiBaseUrl(): string {
  if (!API_BASE) {
    throw new ApiError(MISSING_API_BASE_URL_MESSAGE);
  }
  return API_BASE;
}

async function getJson<T>(path: string): Promise<T> {
  const apiBaseUrl = ensureApiBaseUrl();
  const response = await fetch(`${apiBaseUrl}${path}`, {
    method: "GET",
    headers: { "Content-Type": "application/json" },
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
      if (response.statusText) {
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
  getHealth: () => getJson<HealthResponse>("/api/v1/health"),
  getStats: async () => {
    try {
      const payload = await getJson<Envelope<StatsData>>("/api/v1/stats");
      return payload.data;
    } catch (error) {
      if (error instanceof ApiError && error.status === 404) {
        return null;
      }
      throw error;
    }
  },
  getSettlementMonths: async (limit: number, offset: number) => {
    const payload = await getJson<Envelope<ListData<SettlementMonthSummary>>>(
      `/api/v1/settlement/months?limit=${limit}&offset=${offset}`,
    );
    return payload.data;
  },
  getSettlementDetail: async (profitMonthId: string) => {
    const payload = await getJson<Envelope<SettlementDetailData>>(
      `/api/v1/settlement/${profitMonthId}`,
    );
    return payload.data;
  },
  getProposals: async () => {
    const payload = await getJson<Envelope<ListData<ProposalSummary>>>("/api/v1/proposals");
    return payload.data;
  },
  getProposal: async (id: string) => {
    const payload = await getJson<Envelope<ProposalDetail>>(`/api/v1/proposals/${id}`);
    return payload.data;
  },
  getProjects: async () => {
    const payload = await getJson<Envelope<ListData<ProjectSummary>>>("/api/v1/projects");
    return payload.data;
  },
  getProject: async (id: string) => {
    const payload = await getJson<Envelope<ProjectDetail>>(`/api/v1/projects/${id}`);
    return payload.data;
  },
  getBounties: async () => {
    const payload = await getJson<Envelope<ListData<BountyPublic>>>("/api/v1/bounties");
    return payload.data;
  },
  getBounty: async (id: string) => {
    const payload = await getJson<Envelope<BountyPublic>>(`/api/v1/bounties/${id}`);
    return payload.data;
  },
};
