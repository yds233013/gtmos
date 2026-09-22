import "server-only";

import { connection } from "next/server";

/** Server-side API access. Server components call FastAPI directly (no browser hop, no CORS). */
const BASE = process.env.API_INTERNAL_URL ?? "http://127.0.0.1:8010";

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
    public path: string,
  ) {
    super(message);
  }
}

export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  await connection(); // data pages render at request time; never prerender against a live API
  let res: Response;
  try {
    res = await fetch(`${BASE}/api/v1${path}`, {
      ...init,
      cache: "no-store",
      headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
    });
  } catch {
    throw new ApiError(503, `The GTMOS API is not reachable at ${BASE}. Is it running?`, path);
  }
  if (!res.ok) {
    let message = res.statusText;
    try {
      const body = (await res.json()) as { error?: string; detail?: string };
      message = body.error ?? body.detail ?? message;
    } catch {
      /* non-JSON error body */
    }
    throw new ApiError(res.status, message, path);
  }
  return (await res.json()) as T;
}

/** Fetch several endpoints in parallel; failures become `null` so one broken panel doesn't blank the page. */
export async function settle<T extends readonly unknown[]>(
  ...calls: { [K in keyof T]: Promise<T[K]> }
): Promise<{ [K in keyof T]: T[K] | null }> {
  const results = await Promise.allSettled(calls);
  return results.map((r) => (r.status === "fulfilled" ? r.value : null)) as { [K in keyof T]: T[K] | null };
}
