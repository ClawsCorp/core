export const AGENT_API_KEY_STORAGE_KEY = "clawscorp_agent_api_key";

export function getAgentApiKey(): string {
  if (typeof window === "undefined") {
    return "";
  }
  return window.localStorage.getItem(AGENT_API_KEY_STORAGE_KEY)?.trim() ?? "";
}

export function setAgentApiKey(value: string): string {
  const trimmed = value.trim();
  if (typeof window !== "undefined") {
    window.localStorage.setItem(AGENT_API_KEY_STORAGE_KEY, trimmed);
  }
  return trimmed;
}

export function clearAgentApiKey(): void {
  if (typeof window !== "undefined") {
    window.localStorage.removeItem(AGENT_API_KEY_STORAGE_KEY);
  }
}
