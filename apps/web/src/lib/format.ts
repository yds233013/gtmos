/** Display formatters. Pure functions, covered by unit tests. */

export function money(value: number | null | undefined, opts: { compact?: boolean } = {}): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  const compact = opts.compact ?? Math.abs(value) >= 100_000;
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    notation: compact ? "compact" : "standard",
    maximumFractionDigits: compact ? 1 : 0,
  }).format(value);
}

export function num(value: number | null | undefined, digits = 0): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  return new Intl.NumberFormat("en-US", { maximumFractionDigits: digits }).format(value);
}

export function pct(value: number | null | undefined, digits = 1): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  return `${(value * 100).toFixed(digits)}%`;
}

export function relTime(iso: string | null | undefined, now: Date = new Date()): string {
  if (!iso) return "—";
  const then = new Date(iso);
  const diff = (now.getTime() - then.getTime()) / 1000;
  const future = diff < 0;
  const s = Math.abs(diff);
  const fmt = (n: number, unit: string) => `${Math.floor(n)}${unit}${future ? " from now" : " ago"}`;
  if (s < 60) return future ? "in <1m" : "just now";
  if (s < 3600) return fmt(s / 60, "m");
  if (s < 86400) return fmt(s / 3600, "h");
  if (s < 86400 * 45) return fmt(s / 86400, "d");
  return then.toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" });
}

export function date(iso: string | null | undefined): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" });
}

export function dateTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleString("en-US", {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

export function titleCase(value: string | null | undefined): string {
  if (!value) return "—";
  return value
    .replace(/_/g, " ")
    .replace(/\b\w/g, (c) => c.toUpperCase())
    .replace(/\bAi\b/g, "AI")
    .replace(/\bMl\b/g, "ML")
    .replace(/\bCrm\b/g, "CRM")
    .replace(/\bPql\b/g, "PQL");
}

export const SEGMENT_LABEL: Record<string, string> = {
  strategic: "Strategic",
  enterprise: "Enterprise",
  mid_market: "Mid-Market",
  smb: "SMB",
};

export function segment(value: string | null | undefined): string {
  return value ? (SEGMENT_LABEL[value] ?? titleCase(value)) : "—";
}
