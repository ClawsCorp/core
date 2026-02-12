export const MISSING_NEXT_PUBLIC_API_URL_MESSAGE =
  "Missing NEXT_PUBLIC_API_URL. Set it in your Vercel environment variables.";

const DEFAULT_EXPLORER_BASE_URL = "https://sepolia.basescan.org/tx/";

export function getApiBaseUrl(): string | undefined {
  const rawValue = process.env.NEXT_PUBLIC_API_URL?.trim();
  return rawValue && rawValue.length > 0 ? rawValue : undefined;
}

export function getExplorerBaseUrl(): string {
  const rawValue = process.env.NEXT_PUBLIC_EXPLORER_BASE_URL?.trim();
  return rawValue && rawValue.length > 0 ? rawValue : DEFAULT_EXPLORER_BASE_URL;
}

export function getExplorerTxUrl(txHash: string): string {
  const normalizedBase = getExplorerBaseUrl().replace(/\/+$/, "");
  if (normalizedBase.endsWith("/tx")) {
    return `${normalizedBase}/${txHash}`;
  }
  return `${normalizedBase}/tx/${txHash}`;
}
