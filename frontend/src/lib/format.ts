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

function pad2(value: number): string {
  return value.toString().padStart(2, "0");
}

export function formatDateTimeShort(value: string | null | undefined): string {
  if (!value) {
    return "—";
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return String(value);
  }
  return `${date.getUTCFullYear()}-${pad2(date.getUTCMonth() + 1)}-${pad2(date.getUTCDate())}, ${pad2(
    date.getUTCHours(),
  )}:${pad2(date.getUTCMinutes())}:${pad2(date.getUTCSeconds())}`;
}

export function formatEntityNumber(prefix: string, num: number | null | undefined): string {
  if (num === null || num === undefined || Number.isNaN(num)) {
    return `${prefix} —`;
  }
  return `${prefix} ${num}`;
}
