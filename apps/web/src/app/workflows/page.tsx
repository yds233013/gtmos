import Link from "next/link";

import { FilterTabs } from "@/components/systems/filter-tabs";
import { duration, spanMs } from "@/components/systems/format";
import { ExecutedBadge, HistoryBadge } from "@/components/systems/history-badge";
import { Mono } from "@/components/systems/mono";
import { DemoBadge, StatusBadge } from "@/components/ui/badge";
import { PageHeader } from "@/components/ui/page-header";
import { Panel } from "@/components/ui/panel";
import { StatCell, StatGrid } from "@/components/ui/stat";
import { EmptyState, ErrorState } from "@/components/ui/states";
import { Table, Td, Th, THead, Tr } from "@/components/ui/table";
import { api, settle } from "@/lib/api";
import { num, pct, relTime } from "@/lib/format";

import type { RunList, RunRow, RunStatus, WorkflowItem } from "./types";
import { WorkflowCard } from "./workflow-card";

export const metadata = { title: "Workflows" };

const STATUS_TABS: { key: "all" | RunStatus; label: string }[] = [
  { key: "all", label: "All" },
  { key: "failed", label: "Failed" },
  { key: "dead_letter", label: "Dead letter" },
  { key: "succeeded", label: "Succeeded" },
  { key: "skipped", label: "Skipped" },
  { key: "running", label: "Running" },
  { key: "queued", label: "Queued" },
];

const GUARANTEES = [
  ["Idempotent", "One run per workflow version and trigger event, enforced by a unique key. Re-delivered webhooks and double clicks never run twice."],
  ["Resumable", "Every step's state is persisted. A retry skips steps that already succeeded and resumes at the failed step."],
  ["Retries with backoff", "Transient errors retry per step up to max attempts with exponential backoff (2s, 8s, 32s … capped at 5m)."],
  ["Dead letter", "Runs that exhaust retries park in dead letter for a human to inspect and retry. Nothing is dropped silently."],
] as const;

function first(v: string | string[] | undefined): string | undefined {
  return Array.isArray(v) ? v[0] : v;
}

function qs(params: Record<string, string | undefined>): string {
  const p = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) if (v) p.set(k, v);
  const s = p.toString();
  return s ? `?${s}` : "";
}

/**
 * Loads the runs table. The executed-only view asks the API to exclude synthetic history; if that
 * filter is unavailable, it falls back to filtering the most recent 500 runs here.
 */
async function loadRuns(status: string, workflow: string | undefined, hideHistory: boolean): Promise<RunList | null> {
  const base = { workflow, limit: "100" };
  const statusParam = status === "all" ? undefined : status;
  if (!hideHistory) {
    const [list, all] = await settle(
      api<RunList>(`/workflow-runs${qs({ ...base, status: statusParam })}`),
      api<RunList>(`/workflow-runs${qs({ workflow, limit: "1" })}`),
    );
    return list ? { items: list.items, counts: all?.counts ?? list.counts } : null;
  }
  const [list, all] = await settle(
    api<RunList>(`/workflow-runs${qs({ ...base, status: statusParam, include_synthetic: "false" })}`),
    api<RunList>(`/workflow-runs${qs({ workflow, limit: "1", include_synthetic: "false" })}`),
  );
  if (list) return { items: list.items, counts: all?.counts ?? list.counts };
  const [recent] = await settle(api<RunList>(`/workflow-runs${qs({ workflow, limit: "500" })}`));
  if (!recent) return null;
  const executed = recent.items.filter((r) => !r.synthetic_history);
  const counts: RunList["counts"] = {};
  for (const r of executed) counts[r.status] = (counts[r.status] ?? 0) + 1;
  return { items: executed.filter((r) => !statusParam || r.status === statusParam).slice(0, 100), counts };
}

export default async function WorkflowsPage(props: PageProps<"/workflows">) {
  const sp = await props.searchParams;
  const status = STATUS_TABS.some((t) => t.key === first(sp.status)) ? (first(sp.status) as string) : "all";
  const workflow = first(sp.workflow) || undefined;
  const hideHistory = first(sp.history) === "hide";

  const [workflows, actions, runs] = await Promise.all([
    settle(api<WorkflowItem[]>("/workflows")).then(([w]) => w),
    settle(api<Record<string, string>>("/workflows/actions")).then(([a]) => a),
    loadRuns(status, workflow, hideHistory),
  ]);

  if (!workflows) {
    return (
      <div className="space-y-6">
        <PageHeader title="Workflows" />
        <ErrorState title="Couldn't load workflows" message="The GTMOS API did not respond. Start the backend and reload." />
      </div>
    );
  }

  const totals = workflows.reduce(
    (acc, w) => {
      for (const [k, v] of Object.entries(w.runs_30d ?? {})) acc[k] = (acc[k] ?? 0) + (v ?? 0);
      return acc;
    },
    {} as Record<string, number>,
  );
  const total30 = Object.values(totals).reduce((a, b) => a + b, 0);
  const executed30 = total30 - (totals.skipped ?? 0);
  const enabled = workflows.filter((w) => w.is_enabled).length;
  const selectedWf = workflow ? workflows.find((w) => w.key === workflow) : undefined;

  const link = (over: Record<string, string | undefined>) =>
    `/workflows${qs({ status: status === "all" ? undefined : status, workflow, history: hideHistory ? "hide" : undefined, ...over })}#runs`;

  const counts = runs?.counts ?? {};
  const countAll = Object.values(counts).reduce((a, b) => a + (b ?? 0), 0);

  return (
    <div className="space-y-6">
      <PageHeader
        title="Workflows"
        eyebrow={
          <span className="inline-flex items-center gap-2">
            Systems · workflow engine <DemoBadge />
          </span>
        }
        description="Event-driven automations: a trigger event, conditions evaluated against the account, then an ordered list of actions. Every run is persisted step by step so it can be inspected, retried and audited."
      />

      <StatGrid>
        <StatCell label="Workflows enabled" value={`${enabled} / ${workflows.length}`} />
        <StatCell label="Runs · 30 days" value={num(total30)} sub={`${num(totals.skipped ?? 0)} skipped by conditions`} />
        <StatCell label="Success rate" value={executed30 ? pct((totals.succeeded ?? 0) / executed30, 1) : "—"} sub="of runs that executed" />
        <StatCell label="Succeeded" value={num(totals.succeeded ?? 0)} />
        <StatCell label="Failed" value={num(totals.failed ?? 0)} sub="retryable" />
        <StatCell label="Dead letter" value={num(totals.dead_letter ?? 0)} sub="retries exhausted" />
      </StatGrid>

      <section aria-labelledby="guarantees" className="rounded-lg border border-border bg-panel">
        <h2 id="guarantees" className="sr-only">
          Engine guarantees
        </h2>
        <dl className="grid gap-px overflow-hidden rounded-lg bg-border sm:grid-cols-2 lg:grid-cols-4">
          {GUARANTEES.map(([term, desc]) => (
            <div key={term} className="bg-panel px-4 py-3">
              <dt className="text-xs font-medium text-text">{term}</dt>
              <dd className="mt-0.5 text-[11px] leading-4 text-muted">{desc}</dd>
            </div>
          ))}
        </dl>
      </section>

      <section aria-labelledby="definitions" className="space-y-3">
        <div className="flex items-baseline justify-between gap-3">
          <h2 id="definitions" className="text-sm font-semibold text-text">
            Definitions
          </h2>
          <span className="text-[11px] text-muted">Trigger → conditions → actions · hover a step for what it does</span>
        </div>
        {workflows.length ? (
          workflows.map((wf) => <WorkflowCard key={wf.id} wf={wf} actions={actions ?? {}} />)
        ) : (
          <Panel>
            <EmptyState title="No workflows defined" description="Seed the database to install the default workflows." />
          </Panel>
        )}
      </section>

      <Panel
        id="runs"
        title={selectedWf ? `Runs · ${selectedWf.name}` : "Runs"}
        description={
          hideHistory
            ? "Executed by the engine in this environment only"
            : "Most recent 100 · synthetic history is seeded illustration; unlabelled runs were executed by the engine"
        }
        bodyClassName="p-0"
        actions={
          <div className="flex flex-wrap items-center justify-end gap-2">
            {selectedWf && (
              <Link href={link({ workflow: undefined })} className="text-xs text-accent-text hover:underline">
                All workflows
              </Link>
            )}
            <Link
              href={link({ history: hideHistory ? undefined : "hide" })}
              className="inline-flex h-7 items-center rounded-md border border-border px-2.5 text-xs text-text hover:bg-panel-2"
              aria-pressed={hideHistory}
            >
              {hideHistory ? "Show synthetic history" : "Hide synthetic history"}
            </Link>
          </div>
        }
      >
        <FilterTabs
          label="Filter runs by status"
          active={status}
          className="px-2"
          tabs={STATUS_TABS.map((t) => ({
            key: t.key,
            label: t.label,
            href: link({ status: t.key === "all" ? undefined : t.key }),
            count: t.key === "all" ? countAll : (counts[t.key] ?? 0),
          }))}
        />
        {!runs ? (
          <div className="p-4">
            <ErrorState title="Couldn't load runs" />
          </div>
        ) : runs.items.length ? (
          <RunsTable runs={runs.items} />
        ) : (
          <EmptyState
            title="No runs match this filter"
            description={
              hideHistory
                ? "No executed runs with this status. Trigger a workflow from an account page, or show synthetic history."
                : "Try another status tab."
            }
          />
        )}
      </Panel>
    </div>
  );
}

function RunsTable({ runs }: { runs: RunRow[] }) {
  return (
    <Table>
      <caption className="sr-only">Workflow runs</caption>
      <THead>
        <tr>
          <Th>Status</Th>
          <Th>Workflow</Th>
          <Th>Account</Th>
          <Th>Created</Th>
          <Th align="right">Duration</Th>
          <Th align="right">Attempt</Th>
          <Th>Error</Th>
          <Th>Correlation</Th>
        </tr>
      </THead>
      <tbody>
        {runs.map((r) => (
          <Tr key={r.id}>
            <Td>
              <div className="flex flex-col items-start gap-1">
                <Link href={`/workflows/runs/${r.id}`} className="hover:opacity-80" aria-label={`Open run ${r.id}`}>
                  <StatusBadge status={r.status} />
                </Link>
                {r.synthetic_history ? <HistoryBadge /> : <ExecutedBadge />}
              </div>
            </Td>
            <Td className="max-w-64">
              <Link href={`/workflows/runs/${r.id}`} className="block truncate text-xs font-medium hover:underline">
                {r.workflow}
              </Link>
            </Td>
            <Td className="text-xs">
              {r.account_id ? (
                <Link href={`/accounts/${r.account_id}`} className="hover:underline">
                  {r.account_name ?? "Account"}
                </Link>
              ) : (
                <span className="text-subtle">—</span>
              )}
            </Td>
            <Td className="whitespace-nowrap text-xs text-muted" title={r.created_at}>
              {relTime(r.created_at)}
            </Td>
            <Td align="right" className="whitespace-nowrap text-xs">
              {duration(spanMs(r.started_at, r.finished_at))}
            </Td>
            <Td align="right" className="text-xs">
              {r.attempt}
            </Td>
            <Td className="max-w-72">
              {r.error ? (
                <span className="line-clamp-2 text-[11px] text-danger" title={r.error}>
                  {r.error}
                </span>
              ) : r.status === "skipped" ? (
                <span className="text-[11px] text-muted">Conditions not met</span>
              ) : (
                <span className="text-subtle">—</span>
              )}
            </Td>
            <Td>
              <Mono>{r.correlation_id}</Mono>
            </Td>
          </Tr>
        ))}
      </tbody>
    </Table>
  );
}
