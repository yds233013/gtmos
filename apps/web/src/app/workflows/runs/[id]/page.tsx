import { CheckCircle2, ChevronLeft, CircleDashed, XCircle } from "lucide-react";
import Link from "next/link";
import { notFound } from "next/navigation";

import { actualLabel, describeCondition } from "@/components/systems/conditions";
import { duration, spanMs } from "@/components/systems/format";
import { ExecutedBadge, HistoryBadge } from "@/components/systems/history-badge";
import { JsonBlock, KeyValues } from "@/components/systems/json-block";
import { Mono } from "@/components/systems/mono";
import { ActionButton } from "@/components/ui/action-button";
import { Badge, StatusBadge } from "@/components/ui/badge";
import { PageHeader } from "@/components/ui/page-header";
import { Panel } from "@/components/ui/panel";
import { StatCell, StatGrid } from "@/components/ui/stat";
import { EmptyState, ErrorState } from "@/components/ui/states";
import { api, ApiError } from "@/lib/api";
import { dateTime, relTime, titleCase } from "@/lib/format";
import { cn } from "@/lib/utils";

import type { ConditionResult, RunDetail, StepRunDetail } from "../../types";

export const metadata = { title: "Workflow run" };

const RETRYABLE = new Set(["failed", "dead_letter"]);

export default async function WorkflowRunPage(props: PageProps<"/workflows/runs/[id]">) {
  const { id } = await props.params;
  let run: RunDetail;
  try {
    run = await api<RunDetail>(`/workflow-runs/${encodeURIComponent(id)}`);
  } catch (e) {
    if (e instanceof ApiError && (e.status === 404 || e.status === 422)) notFound();
    return (
      <div className="space-y-6">
        <PageHeader title="Workflow run" />
        <ErrorState title="Couldn't load this run" message={e instanceof Error ? e.message : undefined} />
      </div>
    );
  }

  const synthetic = run.synthetic_history;
  const canRetry = RETRYABLE.has(run.status);
  const steps = [...(run.steps ?? [])].sort((a, b) => a.position - b.position);
  const conditions = run.condition_results ?? [];
  const trigger = run.trigger_event ?? {};
  const triggerType = typeof trigger.type === "string" ? trigger.type : run.workflow?.trigger_type;
  const eventId = typeof trigger.event_id === "string" ? trigger.event_id : null;
  const totalMs = spanMs(run.started_at, run.finished_at);
  const retriedSteps = steps.filter((s) => s.attempts > 1).length;

  return (
    <div className="space-y-6">
      <div>
        <Link href="/workflows#runs" className="inline-flex items-center gap-1 text-xs text-muted hover:text-text">
          <ChevronLeft className="size-3.5" aria-hidden />
          Workflows
        </Link>
      </div>
      <PageHeader
        title={run.workflow?.name ?? "Workflow run"}
        eyebrow={
          <span className="inline-flex flex-wrap items-center gap-2">
            Workflow run <StatusBadge status={run.status} />
            {synthetic ? <HistoryBadge /> : <ExecutedBadge />}
          </span>
        }
        description={
          synthetic
            ? "This run is seeded illustrative history: it shows what the engine records, but it was not executed here and cannot be retried."
            : "Executed by the GTMOS workflow engine. Every step's input, output, attempts and logs are persisted below."
        }
        actions={
          canRetry ? (
            synthetic ? (
              <span className="max-w-56 text-right text-[11px] text-muted">Synthetic history cannot be retried.</span>
            ) : (
              <ActionButton path={`/workflow-runs/${run.id}/retry`} variant="primary" size="md" confirmLabel="Confirm retry">
                Retry from failed step
              </ActionButton>
            )
          ) : null
        }
      />

      {run.error && (
        <div role="alert" className="rounded-lg border border-danger/30 bg-danger-soft px-4 py-3 text-xs">
          <span className="font-medium text-danger">{run.status === "dead_letter" ? "Dead-lettered: " : "Failed: "}</span>
          <span className="text-text">{run.error}</span>
        </div>
      )}

      <StatGrid>
        <StatCell label="Status" value={<StatusBadge status={run.status} />} sub={`attempt ${run.attempt}`} />
        <StatCell
          label="Account"
          value={
            run.account ? (
              <Link href={`/accounts/${run.account.id}`} className="block truncate text-base hover:underline">
                {run.account.name}
              </Link>
            ) : (
              "—"
            )
          }
        />
        <StatCell label="Duration" value={duration(totalMs)} sub={`${steps.length} steps`} />
        <StatCell label="Retried steps" value={String(retriedSteps)} sub="needed >1 attempt" />
        <StatCell label="Started" value={<span className="text-base">{dateTime(run.started_at)}</span>} sub={relTime(run.started_at)} />
        <StatCell label="Finished" value={<span className="text-base">{dateTime(run.finished_at)}</span>} sub={relTime(run.finished_at)} />
      </StatGrid>

      <div className="grid gap-4 lg:grid-cols-3">
        <Panel
          title="Step timeline"
          description="Executed in order; a failed step stops the run and later steps are skipped until retried"
          className="lg:col-span-2"
        >
          {steps.length ? (
            <ol className="relative">
              {steps.map((s, i) => (
                <StepItem key={s.id} step={s} last={i === steps.length - 1} synthetic={synthetic} />
              ))}
            </ol>
          ) : (
            <EmptyState
              title="No steps executed"
              description={run.status === "skipped" ? "Conditions were not met, so no actions ran." : "The run has not started any steps yet."}
            />
          )}
        </Panel>

        <div className="space-y-4">
          <Panel title="Identity & idempotency">
            <dl className="space-y-2.5 text-xs">
              <div>
                <dt className="text-muted">Workflow</dt>
                <dd className="mt-0.5 text-text">
                  {run.workflow?.name ?? run.workflow_key ?? "—"}{" "}
                  {run.workflow_version !== undefined && <Badge>v{run.workflow_version}</Badge>}
                </dd>
              </div>
              <div>
                <dt className="text-muted">Correlation id</dt>
                <dd className="mt-0.5">
                  <Mono className="text-text">{run.correlation_id}</Mono>
                </dd>
              </div>
              <div>
                <dt className="text-muted">Idempotency key</dt>
                <dd className="mt-0.5">
                  <Mono className="text-text">{run.idempotency_key}</Mono>
                </dd>
              </div>
              <div>
                <dt className="text-muted">Run id</dt>
                <dd className="mt-0.5">
                  <Mono>{run.id}</Mono>
                </dd>
              </div>
            </dl>
            <p className="mt-3 border-t border-border pt-3 text-[11px] leading-4 text-muted">
              The idempotency key is <span className="font-mono">workflow : version : trigger type : event id</span> and is unique in
              Postgres, so a re-delivered webhook or a double click cannot start a second run for the same event. The correlation id
              ties this run to the CRM syncs, drafts and audit events it produced.
            </p>
          </Panel>

          <Panel title="Conditions" description="Evaluated against the account when the run was created">
            {conditions.length ? (
              <ul className="space-y-2">
                {conditions.map((c, i) => (
                  <ConditionRow key={i} c={c} />
                ))}
              </ul>
            ) : (
              <p className="text-xs text-muted">This workflow has no conditions; every matching trigger event runs.</p>
            )}
          </Panel>

          <Panel title="Trigger event" description={eventId ? undefined : "What started this run"}>
            <dl className="mb-3 grid grid-cols-[auto_minmax(0,1fr)] gap-x-3 gap-y-1 text-xs">
              <dt className="text-muted">Type</dt>
              <dd className="font-mono text-text">{triggerType ?? "—"}</dd>
              {eventId && (
                <>
                  <dt className="text-muted">Event id</dt>
                  <dd>
                    <Mono>{eventId}</Mono>
                  </dd>
                </>
              )}
              <dt className="text-muted">Received</dt>
              <dd className="text-text">{dateTime(run.created_at)}</dd>
            </dl>
            <JsonBlock value={trigger} summary="Event payload" />
          </Panel>

          <Panel title="Guarantees">
            <ul className="space-y-2 text-[11px] leading-4 text-muted">
              <li>
                <span className="font-medium text-text">Idempotent.</span> One run per trigger event and workflow version.
              </li>
              <li>
                <span className="font-medium text-text">Resumable.</span> Retrying keeps succeeded steps and resumes at the failed one.
              </li>
              <li>
                <span className="font-medium text-text">Retries with backoff.</span> Transient errors retry per step up to max attempts
                with exponential backoff.
              </li>
              <li>
                <span className="font-medium text-text">Dead letter.</span> Exhausted retries park the run for a human instead of
                dropping it.
              </li>
            </ul>
          </Panel>
        </div>
      </div>
    </div>
  );
}

function ConditionRow({ c }: { c: ConditionResult }) {
  const label = c.field && c.op ? describeCondition({ field: c.field, op: c.op, value: c.expected }) : c.condition;
  return (
    <li className="flex items-start gap-2 text-xs">
      {c.passed ? (
        <CheckCircle2 className="mt-0.5 size-3.5 shrink-0 text-success" aria-label="Passed" />
      ) : (
        <XCircle className="mt-0.5 size-3.5 shrink-0 text-danger" aria-label="Failed" />
      )}
      <div className="min-w-0">
        <div className="text-text">{label}</div>
        <div className="text-[11px] text-muted">
          actual: <span className="font-mono text-text">{actualLabel(c.field, c.actual)}</span>
          <span className={cn("ml-2 font-medium", c.passed ? "text-success" : "text-danger")}>{c.passed ? "pass" : "fail"}</span>
        </div>
      </div>
    </li>
  );
}

const STEP_ICON_TONE: Record<string, string> = {
  succeeded: "border-success bg-success-soft text-success",
  failed: "border-danger bg-danger-soft text-danger",
  running: "border-info bg-info-soft text-info",
};

const LOG_TONE: Record<string, string> = { error: "text-danger", warn: "text-warning", warning: "text-warning" };

function StepItem({ step: s, last, synthetic }: { step: StepRunDetail; last: boolean; synthetic: boolean }) {
  const output = Object.fromEntries(Object.entries(s.output ?? {}).filter(([k]) => !(synthetic && k === "synthetic_history")));
  const input = s.input ?? {};
  const logs = s.logs ?? [];
  return (
    <li className="relative flex gap-3 pb-5 last:pb-0">
      {!last && <span aria-hidden className="absolute top-6 bottom-0 left-[11px] w-px bg-border" />}
      <span
        aria-hidden
        className={cn(
          "tabular relative z-10 grid size-6 shrink-0 place-items-center rounded-full border text-[11px] font-medium",
          STEP_ICON_TONE[s.status] ?? "border-border bg-panel-2 text-muted",
        )}
      >
        {s.status === "pending" || s.status === "queued" ? <CircleDashed className="size-3" /> : s.position + 1}
      </span>
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
          <span className="text-sm font-medium text-text">{titleCase(s.action)}</span>
          <Mono>{s.step_key}</Mono>
          <StatusBadge status={s.status} />
          <span className="ml-auto flex items-center gap-3 text-[11px] text-muted">
            <span className={cn("tabular", s.attempts > 1 && "font-medium text-warning")} title="Attempts used / max attempts">
              {s.attempts}/{s.max_attempts} attempts
            </span>
            <span className="tabular">{duration(s.duration_ms)}</span>
          </span>
        </div>
        {s.error && <p className="mt-1.5 rounded border border-danger/30 bg-danger-soft px-2 py-1 text-[11px] text-danger">{s.error}</p>}
        {(Object.keys(output).length > 0 || Object.keys(input).length > 0) && (
          <div className="mt-2 grid gap-3 sm:grid-cols-2">
            {Object.keys(input).length > 0 && (
              <div>
                <div className="mb-1 text-[10px] font-medium uppercase tracking-wide text-subtle">Input</div>
                <KeyValues data={input} />
              </div>
            )}
            {Object.keys(output).length > 0 && (
              <div>
                <div className="mb-1 text-[10px] font-medium uppercase tracking-wide text-subtle">Output</div>
                <KeyValues data={output} />
              </div>
            )}
          </div>
        )}
        {logs.length > 0 && (
          <ul className="mt-2 space-y-0.5 rounded bg-panel-2 px-2 py-1.5 font-mono text-[11px]" aria-label={`Logs for ${s.step_key}`}>
            {logs.map((l, i) => (
              <li key={i} className="flex gap-2">
                <span className="shrink-0 text-subtle">{l.at ? new Date(l.at).toLocaleTimeString("en-US", { hour12: false }) : "--:--:--"}</span>
                <span className={cn("w-10 shrink-0 uppercase", LOG_TONE[l.level] ?? "text-muted")}>{l.level}</span>
                <span className="min-w-0 break-words text-text">{l.msg}</span>
              </li>
            ))}
          </ul>
        )}
      </div>
    </li>
  );
}
