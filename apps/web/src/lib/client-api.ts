/** Browser-side API calls go through the Next.js rewrite at /api/v1 (same origin). */
export const DEMO_ACTOR = "demo.operator@sentinel-ai.example";

export class ClientApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}

export async function clientApi<T>(path: string, init?: { method?: string; body?: unknown }): Promise<T> {
  const res = await fetch(`/api/v1${path}`, {
    method: init?.method ?? "GET",
    headers: { "Content-Type": "application/json", "X-GTMOS-Actor": DEMO_ACTOR },
    body: init?.body !== undefined ? JSON.stringify(init.body) : undefined,
  });
  const text = await res.text();
  const data = text ? (JSON.parse(text) as unknown) : null;
  if (!res.ok) {
    const msg =
      (data as { error?: string; detail?: string } | null)?.error ??
      (data as { detail?: string } | null)?.detail ??
      res.statusText;
    throw new ClientApiError(res.status, typeof msg === "string" ? msg : JSON.stringify(msg));
  }
  return data as T;
}
