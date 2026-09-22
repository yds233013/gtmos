/** Helpers for searchParams-driven (server-rendered) filters. Pure; safe on server and client. */

export type SearchParams = Record<string, string | string[] | undefined>;

/** First value of a search param (Next gives `string[]` when a key repeats). */
export function first(value: string | string[] | undefined): string | undefined {
  const v = Array.isArray(value) ? value[0] : value;
  return v === undefined || v === "" ? undefined : v;
}

/** Parse a positive integer param, falling back when missing or invalid. */
export function intParam(value: string | string[] | undefined, fallback: number, min = 1, max = 10_000): number {
  const n = Number.parseInt(first(value) ?? "", 10);
  if (!Number.isFinite(n)) return fallback;
  return Math.min(max, Math.max(min, n));
}

/** Only accept a param if it is one of the allowed values. */
export function oneOf<T extends string>(value: string | string[] | undefined, allowed: readonly T[]): T | undefined {
  const v = first(value);
  return v !== undefined && (allowed as readonly string[]).includes(v) ? (v as T) : undefined;
}

/**
 * Build `base?query` from the current params plus overrides. `null`/`undefined`/"" removes a key.
 * Any change other than `page` resets pagination.
 */
export function hrefWith(
  base: string,
  params: Record<string, string | undefined>,
  overrides: Record<string, string | number | null | undefined> = {},
): string {
  const next = new URLSearchParams();
  const merged: Record<string, string | number | null | undefined> = { ...params, ...overrides };
  if (!("page" in overrides)) delete merged.page;
  for (const [k, v] of Object.entries(merged)) {
    if (v === null || v === undefined || v === "") continue;
    next.set(k, String(v));
  }
  const qs = next.toString();
  return qs ? `${base}?${qs}` : base;
}

/** Query string for the API from a flat record, skipping empty values. */
export function apiQuery(params: Record<string, string | number | undefined | null>): string {
  const q = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v === null || v === undefined || v === "") continue;
    q.set(k, String(v));
  }
  return q.toString();
}
