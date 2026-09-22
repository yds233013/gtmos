"use client";

import { CheckCircle2, Play, XCircle } from "lucide-react";
import { useId, useState } from "react";

import { actualLabel, describeCondition } from "@/components/systems/conditions";
import { Badge, StatusBadge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { clientApi } from "@/lib/client-api";
import { segment as segmentLabel } from "@/lib/format";
import { cn } from "@/lib/utils";

import { destinationLabel } from "./destination";
import type { SimulationInput, SimulationResult } from "./types";

const SEGMENTS = ["strategic", "enterprise", "mid_market", "smb"] as const;
const REGIONS = ["NA", "EMEA", "APAC", "LATAM"] as const;

const PRESETS: { label: string; input: SimulationInput }[] = [
  { label: "Enterprise NA, hot", input: { segment: "enterprise", region: "NA", icp_score: 86, intent_score: 72, is_customer: false, owner_id: null } },
  { label: "Existing customer", input: { segment: "enterprise", region: "EMEA", icp_score: 70, intent_score: 30, is_customer: true, owner_id: null } },
  { label: "Mid-market NA", input: { segment: "mid_market", region: "NA", icp_score: 68, intent_score: 64, is_customer: false, owner_id: null } },
  { label: "SMB APAC", input: { segment: "smb", region: "APAC", icp_score: 55, intent_score: 20, is_customer: false, owner_id: null } },
];

const inputCls =
  "h-8 w-full rounded-md border border-border bg-panel px-2 text-sm text-text focus:outline-none focus-visible:ring-2 focus-visible:ring-accent/40";

export function RoutingSimulator({
  users,
  ruleNames,
}: {
  users: { id: string; name: string; team: string | null; is_active: boolean }[];
  ruleNames: Record<string, string>;
}) {
  const id = useId();
  const [form, setForm] = useState<SimulationInput>(PRESETS[0].input);
  const [result, setResult] = useState<SimulationResult | null>(null);
  const [ranWith, setRanWith] = useState<SimulationInput | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const userNames = Object.fromEntries(users.map((u) => [u.id, u.name]));

  async function run(input: SimulationInput) {
    setBusy(true);
    setError(null);
    try {
      const body: SimulationInput = { ...input, owner_id: input.owner_id || null };
      const res = await clientApi<SimulationResult>("/routing/simulate", { method: "POST", body });
      setResult(res);
      setRanWith(input);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Simulation failed");
    } finally {
      setBusy(false);
    }
  }

  function set<K extends keyof SimulationInput>(k: K, v: SimulationInput[K]) {
    setForm((f) => ({ ...f, [k]: v }));
  }

  const stale = result && ranWith && JSON.stringify(ranWith) !== JSON.stringify(form);

  return (
    <div className="grid gap-4 lg:grid-cols-[minmax(0,20rem)_minmax(0,1fr)]">
      <form
        className="space-y-3"
        onSubmit={(e) => {
          e.preventDefault();
          void run(form);
        }}
        aria-label="Routing simulation input"
      >
        <div>
          <div className="mb-1.5 text-[11px] font-medium uppercase tracking-wide text-muted">Presets</div>
          <div className="flex flex-wrap gap-1.5">
            {PRESETS.map((p) => (
              <button
                key={p.label}
                type="button"
                onClick={() => {
                  setForm(p.input);
                  void run(p.input);
                }}
                className="rounded border border-border px-2 py-0.5 text-[11px] text-muted hover:bg-panel-2 hover:text-text"
              >
                {p.label}
              </button>
            ))}
          </div>
        </div>
        <div className="grid grid-cols-2 gap-3">
          <label className="block text-xs text-muted" htmlFor={`${id}-segment`}>
            Segment
            <select
              id={`${id}-segment`}
              className={cn(inputCls, "mt-1")}
              value={form.segment ?? ""}
              onChange={(e) => set("segment", (e.target.value || null) as SimulationInput["segment"])}
            >
              <option value="">Unknown</option>
              {SEGMENTS.map((s) => (
                <option key={s} value={s}>
                  {segmentLabel(s)}
                </option>
              ))}
            </select>
          </label>
          <label className="block text-xs text-muted" htmlFor={`${id}-region`}>
            Region
            <select
              id={`${id}-region`}
              className={cn(inputCls, "mt-1")}
              value={form.region ?? ""}
              onChange={(e) => set("region", (e.target.value || null) as SimulationInput["region"])}
            >
              <option value="">Unknown</option>
              {REGIONS.map((r) => (
                <option key={r} value={r}>
                  {r}
                </option>
              ))}
            </select>
          </label>
        </div>
        <ScoreInput id={`${id}-icp`} label="ICP score" value={form.icp_score} onChange={(v) => set("icp_score", v)} />
        <ScoreInput id={`${id}-intent`} label="Intent score" value={form.intent_score} onChange={(v) => set("intent_score", v)} />
        <label className="block text-xs text-muted" htmlFor={`${id}-owner`}>
          Existing owner
          <select
            id={`${id}-owner`}
            className={cn(inputCls, "mt-1")}
            value={form.owner_id ?? ""}
            onChange={(e) => set("owner_id", e.target.value || null)}
          >
            <option value="">None (unowned)</option>
            {users.map((u) => (
              <option key={u.id} value={u.id}>
                {u.name}
                {u.team ? ` · ${u.team}` : ""}
                {u.is_active ? "" : " (inactive)"}
              </option>
            ))}
          </select>
        </label>
        <label className="flex items-center gap-2 text-xs text-text">
          <input
            type="checkbox"
            checked={form.is_customer}
            onChange={(e) => set("is_customer", e.target.checked)}
            className="size-3.5 accent-[var(--accent)]"
          />
          Existing customer
        </label>
        <Button type="submit" variant="primary" disabled={busy} aria-busy={busy} className="w-full">
          <Play className="size-3.5" aria-hidden />
          {busy ? "Routing…" : "Simulate routing"}
        </Button>
        <p className="text-[11px] text-muted">Dry run against the live rule set. Nothing is assigned or written.</p>
      </form>

      <div aria-live="polite" className="min-w-0">
        {error && (
          <p role="alert" className="rounded-md border border-danger/30 bg-danger-soft px-3 py-2 text-xs text-danger">
            {error}
          </p>
        )}
        {!result && !error && (
          <div className="grid h-full min-h-40 place-items-center rounded-md border border-dashed border-border p-6 text-center text-xs text-muted">
            Pick a preset or describe an account, then simulate to see which rule wins, who gets it, and why.
          </div>
        )}
        {result && (
          <div className={cn("space-y-4", stale && "opacity-60")}>
            {stale && <p className="text-[11px] text-warning">Inputs changed since this result. Simulate again to refresh.</p>}
            <div className="grid grid-cols-2 gap-px overflow-hidden rounded-md border border-border bg-border sm:grid-cols-3">
              <div className="bg-panel px-3 py-2">
                <div className="text-[11px] text-muted">Outcome</div>
                <div className="mt-1">
                  <StatusBadge status={result.outcome} />
                </div>
              </div>
              <div className="bg-panel px-3 py-2">
                <div className="text-[11px] text-muted">Owner</div>
                <div className="mt-0.5 truncate text-sm font-semibold text-text">{result.assigned_to ?? "RevOps triage"}</div>
              </div>
              <div className="col-span-2 bg-panel px-3 py-2 sm:col-span-1">
                <div className="text-[11px] text-muted">Winning rule</div>
                <div className="mt-0.5 truncate text-xs font-medium text-text" title={result.rule ?? undefined}>
                  {result.rule ? (ruleNames[result.rule] ?? result.rule) : "None matched"}
                </div>
              </div>
            </div>

            <section>
              <h3 className="mb-1.5 text-[11px] font-medium uppercase tracking-wide text-muted">Explanation</h3>
              <ol className="space-y-1.5">
                {result.explanation.map((line, i) => (
                  <li key={i} className="flex gap-2 text-xs text-text">
                    <span className="tabular grid size-4 shrink-0 place-items-center rounded-full bg-panel-2 text-[10px] text-muted">
                      {i + 1}
                    </span>
                    <span>{line}</span>
                  </li>
                ))}
              </ol>
            </section>

            {result.matched.length > 0 && (
              <section>
                <h3 className="mb-1.5 text-[11px] font-medium uppercase tracking-wide text-muted">
                  Matched rules · {result.matched.length}
                </h3>
                <ul className="space-y-2">
                  {result.matched.map((m, i) => (
                    <li key={m.rule} className="rounded-md border border-border px-3 py-2">
                      <div className="flex flex-wrap items-center gap-2 text-xs">
                        <span className="font-medium text-text">{m.name}</span>
                        <Badge>P{m.priority}</Badge>
                        {i === 0 ? <Badge tone="success">winner</Badge> : <Badge>outranked</Badge>}
                      </div>
                      <ul className="mt-1.5 space-y-0.5">
                        {(m.conditions ?? []).map((c, j) => (
                          <li key={j} className="flex items-center gap-1.5 text-[11px] text-muted">
                            {c.passed ? (
                              <CheckCircle2 className="size-3 text-success" aria-label="passed" />
                            ) : (
                              <XCircle className="size-3 text-danger" aria-label="failed" />
                            )}
                            {describeCondition({ field: c.field, op: c.op, value: c.expected })}
                            <span className="text-subtle">
                              (actual <span className="font-mono text-text">{actualLabel(c.field, c.actual)}</span>)
                            </span>
                          </li>
                        ))}
                      </ul>
                    </li>
                  ))}
                </ul>
              </section>
            )}

            <section>
              <h3 className="mb-1.5 text-[11px] font-medium uppercase tracking-wide text-muted">Conflicts · {result.conflicts.length}</h3>
              {result.conflicts.length ? (
                <ul className="space-y-1.5">
                  {result.conflicts.map((c) => (
                    <li key={c.rule} className="rounded-md border border-warning/30 bg-warning-soft px-3 py-2 text-xs">
                      <span className="font-medium text-text">{c.name}</span>
                      <span className="text-muted"> would have sent it to {destinationLabel(c.destination, userNames)}; lost because </span>
                      <span className="text-text">{c.lost_because}</span>
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="text-xs text-muted">No competing rule pointed somewhere else.</p>
              )}
            </section>
          </div>
        )}
      </div>
    </div>
  );
}

function ScoreInput({ id, label, value, onChange }: { id: string; label: string; value: number; onChange: (v: number) => void }) {
  return (
    <div>
      <div className="flex items-center justify-between text-xs text-muted">
        <label htmlFor={id}>{label}</label>
        <input
          type="number"
          min={0}
          max={100}
          value={value}
          aria-label={`${label} value`}
          onChange={(e) => onChange(Math.max(0, Math.min(100, Number(e.target.value) || 0)))}
          className="tabular h-6 w-14 rounded border border-border bg-panel px-1.5 text-right text-xs text-text"
        />
      </div>
      <input
        id={id}
        type="range"
        min={0}
        max={100}
        value={value}
        onChange={(e) => onChange(Number(e.target.value))}
        className="mt-1 w-full accent-[var(--accent)]"
      />
    </div>
  );
}
