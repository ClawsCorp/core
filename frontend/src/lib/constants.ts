export const MISSING_API_BASE_URL_MESSAGE =
  "Missing NEXT_PUBLIC_API_URL. Set it in Vercel env vars.";

export function getApiBaseUrl(): string | undefined {
  const envBase = process.env.NEXT_PUBLIC_API_URL?.trim();
  return envBase && envBase.length > 0 ? envBase : undefined;
}
