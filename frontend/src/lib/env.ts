export const MISSING_NEXT_PUBLIC_API_URL_MESSAGE =
  "Missing NEXT_PUBLIC_API_URL. Set it in your Vercel environment variables.";

export function getApiBaseUrl(): string | undefined {
  const rawValue = process.env.NEXT_PUBLIC_API_URL?.trim();
  return rawValue && rawValue.length > 0 ? rawValue : undefined;
}
