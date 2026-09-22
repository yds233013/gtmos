import { ArrowDown, ArrowRight, Filter, RotateCcw, Zap } from "lucide-react";
import Link from "next/link";

import { describeCondition } from "@/components/systems/conditions";
import { Mono } from "@/components/systems/mono";
import { ActionButton } from "@/components/ui/action-button";
import { Badge } from "@/components/ui/badge";
import { num, pct, relTime, titleCase } from "@/lib/format";
import { cn } from "@/lib/utils";

import type { WorkflowItem } from "./types";

const DEFAULT_MAX_ATTEMPTS = 3;

function Stage({
  label,
  icon: Icon,
  children,
  className,
}: {
  label: string;
  icon: typeof Zap;
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <div className={cn("min-w-0 rounded-md border border-border bg-panel-2/50 p-3", className)}>
      <div className="mb-2 flex items-center gap-1.5 text-[11px] font-medium uppercase tracking-wide text-muted">
        <Icon className="size-3.5" aria-hidden />
        {label}
      </div>
      {children}
    </div>
  );
}

function Connector() {
  return (
    <div className="flex items-center justify-center text-subtle" aria-hidden>
      <ArrowDown className="size-4 lg:hidden" />
      <ArrowRight className="hidden size-4 lg:block" />
    </div>
  );
}

export function WorkflowCard({ wf, actions }: { wf: WorkflowItem; actions: Record<string, string> }) {
  const r = wf.runs_30d ?? {};
  const total = Object.values(r).reduce((a, b) => a + (b ?? 0), 0);
  const skipped = r.skipped ?? 0;
  const executed = total - skipped;
  const succeeded = r.succeeded ?? 0;
  const failed = r.failed ?? 0;
  const dead = r.dead_letter ?? 0;
  const filters = wf.definition.trigger.filters ?? [];
  const conditions = wf.definition.conditions ?? [];

  return (
    <article className="overflow-hidden rounded-lg border border-border bg-panel" aria-labelledby={`wf-${wf.key}`}>
      <header className="flex flex-col gap-3 border-b border-border px-4 py-3 sm:flex-row sm:items-start sm:justify-between">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <h3 id={`wf-${wf.key}`} className="text-sm font-semibold text-text">
              {wf.name}
            </h3>
            {wf.is_enabled ? <Badge tone="success">Enabled</Badge> : <Badge>Disabled</Badge>}
            <Badge>v{wf.version}</Badge>
          </div>
          {wf.description && <p className="mt-1 max-w-3xl text-xs text-muted">{wf.description}</p>}
          <Mono className="mt-1 block">{wf.key}</Mono>
        </div>
        <div className="flex shrink-0 items-start gap-2">
          <Link
            href={`/workflows?workflow=${encodeURIComponent(wf.key)}#runs`}
            className="inline-flex h-7 items-center rounded-md px-2.5 text-xs text-accent-text hover:bg-panel-2"
          >
            View runs
          </Link>
          <ActionButton
            path={`/workflows/${encodeURIComponent(wf.key)}`}
            method="PATCH"
            body={{ is_enabled: !wf.is_enabled }}
            variant={wf.is_enabled ? "secondary" : "primary"}
            confirmLabel={wf.is_enabled ? "Confirm disable" : undefined}
          >
            {wf.is_enabled ? "Disable" : "Enable"}
          </ActionButton>
        </div>
      </header>

      <div className="grid gap-2 p-4 lg:grid-cols-[minmax(0,13rem)_auto_minmax(0,15rem)_auto_minmax(0,1fr)]">
        <Stage label="Trigger" icon={Zap}>
          <div className="font-mono text-xs font-medium text-text">{wf.definition.trigger.type}</div>
          {filters.length ? (
            <ul className="mt-1.5 space-y-1">
              {filters.map((f, i) => (
                <li key={i} className="text-[11px] text-muted">
                  where {describeCondition(f)}
                </li>
              ))}
            </ul>
          ) : (
            <p className="mt-1.5 text-[11px] text-muted">Every event of this type</p>
          )}
        </Stage>
        <Connector />
        <Stage label="Conditions" icon={Filter}>
          {conditions.length ? (
            <ul className="space-y-1">
              {conditions.map((c, i) => (
                <li key={i} className="flex items-start gap-1.5 text-xs text-text">
                  {i > 0 && <span className="text-[10px] font-medium uppercase text-subtle">and</span>}
                  <span>{describeCondition(c)}</span>
                </li>
              ))}
            </ul>
          ) : (
            <p className="text-xs text-muted">None: every matching event runs</p>
          )}
          <p className="mt-1.5 text-[11px] text-subtle">Not met → run recorded as skipped</p>
        </Stage>
        <Connector />
        <Stage label={`Actions · ${wf.definition.steps.length} steps`} icon={ArrowRight}>
          <ol className="flex flex-wrap items-center gap-1.5">
            {wf.definition.steps.map((s, i) => {
              const max = s.max_attempts ?? DEFAULT_MAX_ATTEMPTS;
              return (
                <li key={s.key} className="flex items-center gap-1.5">
                  {i > 0 && <ArrowRight className="size-3 text-subtle" aria-hidden />}
                  <span
                    title={`${actions[s.action] ?? s.action}${s.params && Object.keys(s.params).length ? ` · ${JSON.stringify(s.params)}` : ""}`}
                    className="inline-flex items-center gap-1.5 rounded border border-border bg-panel px-1.5 py-1 text-xs text-text"
                  >
                    <span className="tabular grid size-4 place-items-center rounded-sm bg-panel-2 text-[10px] font-medium text-muted">
                      {i + 1}
                    </span>
                    {titleCase(s.action)}
                    {max !== DEFAULT_MAX_ATTEMPTS && (
                      <span className="inline-flex items-center gap-0.5 text-[10px] text-muted" title={`Up to ${max} attempts`}>
                        <RotateCcw className="size-2.5" aria-hidden />
                        {max}
                      </span>
                    )}
                    {s.continue_on_failure && <span className="text-[10px] text-warning">continues on failure</span>}
                  </span>
                </li>
              );
            })}
          </ol>
          <p className="mt-2 text-[11px] text-subtle">
            Each step retries transient errors up to {DEFAULT_MAX_ATTEMPTS} attempts unless noted, with exponential backoff.
          </p>
        </Stage>
      </div>

      <footer className="grid grid-cols-3 gap-px border-t border-border bg-border text-xs sm:grid-cols-6">
        {[
          ["Runs · 30d", num(total)],
          ["Success rate", executed ? pct(succeeded / executed, 0) : "—"],
          ["Succeeded", num(succeeded)],
          ["Failed", num(failed)],
          ["Dead letter", num(dead)],
          ["Last run", relTime(wf.last_run_at)],
        ].map(([label, value]) => (
          <div key={label} className="bg-panel px-4 py-2">
            <div className="text-[11px] text-muted">{label}</div>
            <div
              className={cn(
                "tabular mt-0.5 font-medium text-text",
                label === "Failed" && failed > 0 && "text-danger",
                label === "Dead letter" && dead > 0 && "text-danger",
              )}
            >
              {value}
            </div>
          </div>
        ))}
      </footer>
    </article>
  );
}
