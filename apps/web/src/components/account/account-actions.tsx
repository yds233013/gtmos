"use client";

import { useRouter } from "next/navigation";
import { useState, useTransition } from "react";

import { Button } from "@/components/ui/button";
import { clientApi } from "@/lib/client-api";

type Result = { title: string; lines: string[]; tone: "ok" | "error" };

export function AccountActions({ accountId }: { accountId: string }) {
  const router = useRouter();
  const [busy, setBusy] = useState<string | null>(null);
  const [, start] = useTransition();
  const [result, setResult] = useState<Result | null>(null);

  async function run(key: string, fn: () => Promise<Result>) {
    setBusy(key);
    try {
      setResult(await fn());
      start(() => router.refresh());
    } catch (e) {
      setResult({ title: "Action failed", lines: [e instanceof Error ? e.message : String(e)], tone: "error" });
    } finally {
      setBusy(null);
    }
  }

  const actions: { key: string; label: string; primary?: boolean; fn: () => Promise<Result> }[] = [
    {
      key: "workflow",
      label: "Run signal → outreach workflow",
      primary: true,
      fn: async () => {
        const r = await clientApi<{ run_id: string; status: string; error: string | null }>(
          `/accounts/${accountId}/workflows/funding-signal-to-outreach/run`,
          { method: "POST" },
        );
        return {
          title: `Workflow run ${r.status}`,
          lines: [r.error ?? "Enrich → rescore → committee → research → draft (approval queue) → route → CRM sync.", `Run id ${r.run_id}`],
          tone: r.status === "failed" || r.status === "dead_letter" ? "error" : "ok",
        };
      },
    },
    {
      key: "enrich",
      label: "Enrich",
      fn: async () => {
        const r = await clientApi<{ run: { status: string; fields_changed: string[]; total_cost_credits: number }; score_before: number; score_after: number }>(
          `/accounts/${accountId}/enrich`,
          { method: "POST" },
        );
        return {
          title: `Enrichment ${r.run.status}`,
          lines: [
            r.run.fields_changed.length ? `Changed: ${r.run.fields_changed.join(", ")}` : "No field changed: existing values confirmed or kept.",
            `Cost ${r.run.total_cost_credits} credits (simulated) · score ${r.score_before} → ${r.score_after}`,
          ],
          tone: "ok",
        };
      },
    },
    {
      key: "rescore",
      label: "Rescore",
      fn: async () => {
        const r = await clientApi<{ before: number; after: number; grade: string; summary: string }>(`/accounts/${accountId}/rescore`, {
          method: "POST",
        });
        return { title: `Score ${r.before} → ${r.after} (${r.grade})`, lines: [r.summary], tone: "ok" };
      },
    },
    {
      key: "route-preview",
      label: "Preview routing",
      fn: async () => {
        const r = await clientApi<{ outcome: string; assigned_to: string | null; explanation: string[] }>(`/accounts/${accountId}/route`, {
          method: "POST",
          body: { apply: false },
        });
        return { title: `Routing preview: ${r.outcome}${r.assigned_to ? ` → ${r.assigned_to}` : ""}`, lines: r.explanation, tone: "ok" };
      },
    },
    {
      key: "route",
      label: "Apply routing",
      fn: async () => {
        const r = await clientApi<{ outcome: string; assigned_to: string | null; explanation: string[] }>(`/accounts/${accountId}/route`, {
          method: "POST",
          body: { apply: true },
        });
        return { title: `Routed: ${r.outcome}${r.assigned_to ? ` → ${r.assigned_to}` : ""}`, lines: r.explanation, tone: "ok" };
      },
    },
  ];

  return (
    <div className="space-y-2">
      <div className="flex flex-wrap gap-2">
        {actions.map((a) => (
          <Button key={a.key} size="sm" variant={a.primary ? "primary" : "secondary"} disabled={!!busy} onClick={() => run(a.key, a.fn)}>
            {busy === a.key ? "Working…" : a.label}
          </Button>
        ))}
      </div>
      {result && (
        <div
          role="status"
          className={
            result.tone === "error"
              ? "rounded-md border border-danger/30 bg-danger-soft px-3 py-2 text-xs"
              : "rounded-md border border-border bg-panel-2 px-3 py-2 text-xs"
          }
        >
          <div className="flex items-start justify-between gap-3">
            <div className={result.tone === "error" ? "font-medium text-danger" : "font-medium"}>{result.title}</div>
            <button type="button" className="text-muted hover:text-text" onClick={() => setResult(null)} aria-label="Dismiss">
              ×
            </button>
          </div>
          <ul className="mt-1 space-y-0.5 text-muted">
            {result.lines.map((l, i) => (
              <li key={i}>{l}</li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
