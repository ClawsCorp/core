const MICRO_USDC_SCALE = 1_000_000;

export function formatMicroUsdc(amountMicroUsdc: number | null | undefined): string {
  if (amountMicroUsdc === null || amountMicroUsdc === undefined || Number.isNaN(amountMicroUsdc)) {
    return "—";
  }

  return `${(amountMicroUsdc / MICRO_USDC_SCALE).toLocaleString("en-US", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })} USDC`;
}

export function formatBoolean(value: boolean): string {
  return value ? "Yes" : "No";
}
