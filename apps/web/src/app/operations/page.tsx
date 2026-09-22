import Link from "next/link";

import { BarTrend } from "@/components/charts/bar-trend";
import { duration, hours } from "@/components/systems/format";
import { HistoryBadge } from "@/components/systems/history-badge";
import { Mono } from "@/components/systems/mono";
import { ActionButton } from "@/components/ui/action-button";
import { Badge, DemoBadge, SimulatedBadge, StatusBadge, StatusDot } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { PageHeader } from "@/components/ui/page-header";
import { Panel } from "@/components/ui/panel";
import { StatCell, StatGrid } from "@/components/ui/stat";
import { EmptyState, ErrorState } from "@/components/ui/states";
import { Table, Td, Th, THead, Tr } from "@/components/ui/table";
import { api, settle } from "@/lib/api";
import { dateTime, num, pct, relTime, titleCase } from "@/lib/format";
import { cn } from "@/lib/utils";

import type { RunList } from "../workflows/types";
import type { Operations, ReverseEtlPreview, WebhookEvent } from "./types";

export const metadata = { title: "Operations" };

const WEBHOOK_STATUSES = ["processed", "failed", "rejected", "dead_letter"] as const;

function rateTone(rate: number | null | undefined, warn: number, crit: number): string {
  if (rate === null || rate === undefined) return "";
  return rate >= crit ? "text-danger" : rate >= warn ? "text-warning" : "";
}

export default async function OperationsPage() {
  const [ops, attentionRuns, events, retl] = await settle(
    api<Operations>("/operations"),
    api<RunList>("/workflow-runs?status=failed&status=dead_letter&limit=500"),
    api<{ items: WebhookEvent[] }>("/webhooks/events?limit=500"),
    api<ReverseEtlPreview>("/integrations/hubspot/reverse-etl/preview?limit=1"),
  );

  if (!ops) {
    return (
      <div className="space-y-6">
        <PageHeader title="Operations" />
        <ErrorState title="Couldn't load operations health" message="The GTMOS API did not respond. Start the backend and reload." />
      </div>
    );
  }

  const { workflows: wf, syncs, webhooks: wh, providers, routing, queue, llm } = ops;
  const syntheticRun = new Map((attentionRuns?.items ?? []).map((r) => [r.id, r.synthetic_history]));
  const syntheticEvent = new Map((events?.items ?? []).map((e) => [e.id, Boolean(e.payload?.synthetic_history)]));
  const syncSeries = [...syncs.recent]
    .reverse()
    .map((s) => ({ label: new Date(s.started_at).toLocaleDateString("en-US", { month: "short", day: "numeric" }), value: s.changed }));
  const webhookWindow = wh.window_days ?? wf.window_days;

  return (
    <div className="space-y-6">
      <PageHeader
        title="Operations"
        eyebrow={
          <span className="inline-flex items-center gap-2">
            Systems · observability · last {wf.window_days} days <DemoBadge />
          </span>
        }
        description="Is the machine healthy? Workflow failures, CRM sync jobs, inbound webhooks, enrichment providers and routing latency in one place. Correlation ids tie a failure to every record it touched."
      />

      <StatGrid>
        <StatCell
          label="Workflow failure rate"
          value={<span className={rateTone(wf.failure_rate, 0.05, 0.15)}>{pct(wf.failure_rate)}</span>}
          sub={`${num(wf.executed)} executed runs`}
        />
        <StatCell label="Dead-lettered runs" value={num(wf.dead_letter_total)} sub={`${num(wf.retried_steps)} steps retried · ${wf.window_days}d`} />
        <StatCell label="Median run duration" value={duration(wf.median_duration_ms)} />
        <StatCell
          label="Sync record failures"
          value={<span className={rateTone(syncs.record_failure_rate, 0.01, 0.05)}>{pct(syncs.record_failure_rate, 2)}</span>}
          sub={`${num(syncs.records_failed)} of ${num(syncs.records_changed + syncs.records_failed)} records`}
        />
        <StatCell
          label="Webhook failure rate"
          value={<span className={rateTone(wh.failure_rate, 0.05, 0.15)}>{pct(wh.failure_rate)}</span>}
          sub={`${num(wh.total)} received · ${num(wh.duplicates_absorbed)} dupes absorbed`}
        />
        <StatCell
          label="Last successful sync"
          value={<span className={cn((syncs.hours_since_success ?? 0) > 26 && "text-danger")}>{hours(syncs.hours_since_success)} ago</span>}
          sub={dateTime(syncs.last_success_at)}
        />
      </StatGrid>

      <Panel
        title="Workflow runs needing attention"
        description="Failed and dead-lettered runs · open one to inspect the failing step and retry"
        bodyClassName="p-0"
        actions={
          <Link href="/workflows?status=dead_letter#runs" className="text-xs text-accent-text hover:underline">
            All runs
          </Link>
        }
      >
        {wf.needs_attention.length ? (
          <Table>
            <caption className="sr-only">Workflow runs needing attention</caption>
            <THead>
              <tr>
                <Th>Status</Th>
                <Th>Workflow</Th>
                <Th>Error</Th>
                <Th>When</Th>
                <Th>Correlation</Th>
              </tr>
            </THead>
            <tbody>
              {wf.needs_attention.slice(0, 10).map((r) => (
                <Tr key={r.run_id}>
                  <Td className="align-top">
                    <div className="flex flex-col items-start gap-1">
                      <StatusBadge status={r.status} />
                      {syntheticRun.get(r.run_id) && <HistoryBadge />}
                    </div>
                  </Td>
                  <Td className="max-w-56 align-top">
                    <Link href={`/workflows/runs/${r.run_id}`} className="text-xs font-medium hover:underline">
                      {r.workflow}
                    </Link>
                    {r.account_id && (
                      <Link href={`/accounts/${r.account_id}`} className="block text-[11px] text-muted hover:underline">
                        View account
                      </Link>
                    )}
                  </Td>
                  <Td className="max-w-md align-top">
                    <span className="line-clamp-2 text-[11px] text-danger" title={r.error ?? undefined}>
                      {r.error ?? <span className="text-muted">No error message recorded</span>}
                    </span>
                  </Td>
                  <Td className="whitespace-nowrap align-top text-[11px] text-muted" title={r.created_at}>
                    {relTime(r.created_at)}
                  </Td>
                  <Td className="align-top">
                    <Mono>{r.correlation_id}</Mono>
                  </Td>
                </Tr>
              ))}
            </tbody>
          </Table>
        ) : (
          <EmptyState title="Nothing needs attention" description="No failed or dead-lettered workflow runs." />
        )}
        {wf.needs_attention.length > 10 && (
          <p className="border-t border-border px-4 py-2 text-[11px] text-muted">
            Showing 10 of {num(wf.needs_attention.length)}.{" "}
            <Link href="/workflows?status=failed#runs" className="text-accent-text hover:underline">
              See all failed runs
            </Link>
          </p>
        )}
      </Panel>

      <div className="grid gap-4 lg:grid-cols-3">
        <Panel
          title="CRM sync jobs"
          description={`${num(syncs.runs)} runs · ${num(syncs.partial_runs)} partial · ${num(syncs.failed_runs)} failed · ${num(syncs.retries)} retries`}
          className="lg:col-span-2"
          bodyClassName="p-0"
          actions={syncs.all_simulated ? <SimulatedBadge /> : undefined}
        >
          {syncs.recent.length ? (
            <Table>
              <caption className="sr-only">Recent CRM sync jobs</caption>
              <THead>
                <tr>
                  <Th>Job</Th>
                  <Th>Status</Th>
                  <Th align="right">Changed</Th>
                  <Th align="right">Failed</Th>
                  <Th align="right">Skipped</Th>
                  <Th align="right">Retries</Th>
                  <Th align="right">Duration</Th>
                  <Th>Started</Th>
                  <Th>Correlation</Th>
                </tr>
              </THead>
              <tbody>
                {syncs.recent.map((s) => (
                  <Tr key={s.id}>
                    <Td className="align-top">
                      <div className="flex flex-wrap items-center gap-1.5">
                        <span className="font-mono text-[11px] text-text">{s.job}</span>
                        {s.is_simulated && <SimulatedBadge />}
                      </div>
                      <div className="mt-0.5 max-w-56 truncate text-[11px] text-muted" title={s.trigger}>
                        {s.trigger.startsWith("workflow:") ? (
                          <Link href={`/workflows/runs/${s.trigger.slice("workflow:".length)}`} className="hover:underline">
                            from workflow run
                          </Link>
                        ) : (
                          titleCase(s.trigger)
                        )}
                      </div>
                      {s.error && <div className="mt-0.5 text-[11px] text-danger">{s.error}</div>}
                    </Td>
                    <Td className="align-top">
                      <StatusBadge status={s.status} />
                    </Td>
                    <Td align="right" className="align-top text-xs">
                      {num(s.changed)}
                    </Td>
                    <Td align="right" className={cn("align-top text-xs", s.failed > 0 && "text-danger")}>
                      {num(s.failed)}
                    </Td>
                    <Td align="right" className="align-top text-xs text-muted">
                      {num(s.skipped)}
                    </Td>
                    <Td align="right" className="align-top text-xs">
                      {num(s.retries)}
                    </Td>
                    <Td align="right" className="whitespace-nowrap align-top text-xs">
                      {duration(s.duration_ms)}
                    </Td>
                    <Td className="whitespace-nowrap align-top text-[11px] text-muted" title={s.started_at}>
                      {relTime(s.started_at)}
                    </Td>
                    <Td className="align-top">{s.correlation_id ? <Mono>{s.correlation_id}</Mono> : "—"}</Td>
                  </Tr>
                ))}
              </tbody>
            </Table>
          ) : (
            <EmptyState title="No sync runs yet" />
          )}
        </Panel>

        <div className="space-y-4">
          <Panel title="Records changed per sync" description="Oldest → newest recent runs">
            {syncSeries.length ? (
              <BarTrend data={syncSeries} valueFormat="number" seriesLabel="Records changed" height={160} />
            ) : (
              <p className="text-xs text-muted">No sync runs.</p>
            )}
          </Panel>
          <Panel
            title="Reverse ETL · HubSpot companies"
            description="Push GTMOS scores and fields to CRM companies"
            actions={retl?.destination_mode === "simulated" ? <SimulatedBadge /> : undefined}
          >
            {retl ? (
              <>
                <dl className="grid grid-cols-2 gap-3 text-xs">
                  {[
                    ["Considered", retl.considered],
                    ["Unchanged", retl.unchanged],
                    ["Would create", retl.would_create],
                    ["Would update", retl.would_update],
                  ].map(([k, v]) => (
                    <div key={k}>
                      <dt className="text-muted">{k}</dt>
                      <dd className="tabular mt-0.5 font-semibold text-text">{num(v as number)}</dd>
                    </div>
                  ))}
                </dl>
                <p className="mt-3 text-[11px] text-muted">
                  Only changed fields are written; unchanged records are skipped. Last run {relTime(retl.last_run?.finished_at)}.
                </p>
                <div className="mt-3">
                  <ActionButton path="/integrations/hubspot/reverse-etl/run">
                    Run sync{retl.destination_mode === "simulated" ? " (simulated)" : ""}
                  </ActionButton>
                </div>
              </>
            ) : (
              <p className="text-xs text-muted">Preview unavailable.</p>
            )}
          </Panel>
        </div>
      </div>

      <div className="grid gap-4 lg:grid-cols-5">
        <Panel
          title="Webhook health"
          description={`By source · last ${webhookWindow} days · p50 ${duration(wh.p50_processing_ms)}, p95 ${duration(wh.p95_processing_ms)} processing`}
          className="lg:col-span-2"
          bodyClassName="p-0"
        >
          {Object.keys(wh.by_source).length ? (
            <Table>
              <caption className="sr-only">Webhook events by source and status</caption>
              <THead>
                <tr>
                  <Th>Source</Th>
                  {WEBHOOK_STATUSES.map((s) => (
                    <Th key={s} align="right">
                      {titleCase(s)}
                    </Th>
                  ))}
                  <Th>Last received</Th>
                </tr>
              </THead>
              <tbody>
                {Object.entries(wh.by_source).map(([src, byStatus]) => {
                  const total = Object.values(byStatus).reduce((a, b) => a + b, 0);
                  const bad = total - (byStatus.processed ?? 0);
                  return (
                    <Tr key={src}>
                      <Td>
                        <div className="flex items-center gap-2">
                          <StatusDot status={bad / Math.max(total, 1) > 0.15 ? "failed" : bad > 0 ? "warning" : "healthy"} />
                          <span className="text-xs font-medium">{titleCase(src)}</span>
                        </div>
                      </Td>
                      {WEBHOOK_STATUSES.map((s) => (
                        <Td key={s} align="right" className={cn("text-xs", s !== "processed" && (byStatus[s] ?? 0) > 0 && "text-danger")}>
                          {num(byStatus[s] ?? 0)}
                        </Td>
                      ))}
                      <Td className="whitespace-nowrap text-[11px] text-muted">{relTime(wh.last_received[src])}</Td>
                    </Tr>
                  );
                })}
              </tbody>
            </Table>
          ) : (
            <EmptyState title="No webhooks received" />
          )}
          <p className="border-t border-border px-4 py-2 text-[11px] text-muted">
            Deliveries are deduplicated by idempotency key: {num(wh.duplicates_absorbed)} re-deliveries were absorbed without
            reprocessing. Unsigned or mis-signed payloads are rejected.
          </p>
        </Panel>

        <Panel
          title="Webhooks needing attention"
          description="Failed, rejected and dead-lettered deliveries · replay reprocesses the stored payload"
          className="lg:col-span-3"
          bodyClassName="p-0"
        >
          {wh.needs_attention.length ? (
            <ul className="divide-y divide-border">
              {wh.needs_attention.slice(0, 8).map((e) => {
                const synthetic = syntheticEvent.get(e.id) ?? false;
                return (
                  <li key={e.id} className="flex flex-col gap-2 px-4 py-2.5 sm:flex-row sm:items-start sm:justify-between">
                    <div className="min-w-0">
                      <div className="flex flex-wrap items-center gap-1.5 text-xs">
                        <span className="font-medium text-text">{titleCase(e.source)}</span>
                        <StatusBadge status={e.status} />
                        {synthetic && <HistoryBadge />}
                        <span className="text-[11px] text-muted">
                          {relTime(e.received_at)} · {e.attempts} attempt{e.attempts === 1 ? "" : "s"}
                        </span>
                      </div>
                      <p className="mt-0.5 text-[11px] text-danger">{e.error ?? "No error recorded"}</p>
                      {e.correlation_id && <Mono>{e.correlation_id}</Mono>}
                    </div>
                    <div className="shrink-0">
                      {synthetic ? (
                        <Button size="sm" disabled title="Synthetic history events are illustrative and cannot be replayed">
                          Replay
                        </Button>
                      ) : (
                        <ActionButton path={`/webhooks/events/${e.id}/replay`}>Replay</ActionButton>
                      )}
                    </div>
                  </li>
                );
              })}
            </ul>
          ) : (
            <EmptyState title="All deliveries processed" description="No failed, rejected or dead-lettered webhooks." />
          )}
          {wh.needs_attention.length > 8 && (
            <p className="border-t border-border px-4 py-2 text-[11px] text-muted">
              Showing 8 of {num(wh.needs_attention.length)}.
            </p>
          )}
        </Panel>
      </div>

      <Panel title="Enrichment providers" description="Waterfall order · providers are tried in sequence until a confident hit" bodyClassName="p-0">
        {providers.length ? (
          <Table>
            <caption className="sr-only">Enrichment provider health</caption>
            <THead>
              <tr>
                <Th>Provider</Th>
                <Th>Status</Th>
                <Th align="right">Attempts</Th>
                <Th align="right">Hit rate</Th>
                <Th align="right">Miss</Th>
                <Th align="right">Low conf.</Th>
                <Th align="right">Error rate</Th>
                <Th align="right">Avg latency</Th>
                <Th align="right">Cost (credits)</Th>
              </tr>
            </THead>
            <tbody>
              {providers.map((p) => {
                const notConfigured = p.attempts > 0 && (p.skipped ?? 0) === p.attempts;
                return (
                  <Tr key={p.provider}>
                    <Td>
                      <div className="text-xs font-medium">{p.name}</div>
                      <Mono>{p.provider}</Mono>
                    </Td>
                    <Td>
                      {notConfigured ? (
                        <Badge title="Every attempt was skipped: no API key configured">not configured</Badge>
                      ) : (
                        <StatusBadge status={p.status} />
                      )}
                    </Td>
                    <Td align="right" className="text-xs">
                      {num(p.attempts)}
                      {(p.skipped ?? 0) > 0 && <div className="text-[11px] text-muted">{num(p.skipped)} skipped</div>}
                    </Td>
                    <Td align="right" className="text-xs">
                      {pct(p.hit_rate)}
                    </Td>
                    <Td align="right" className="text-xs text-muted">
                      {num(p.miss)}
                    </Td>
                    <Td align="right" className="text-xs text-muted">
                      {num(p.low_confidence)}
                    </Td>
                    <Td align="right" className={cn("text-xs", rateTone(p.error_rate, 0.05, 0.15))}>
                      {pct(p.error_rate)}
                    </Td>
                    <Td align="right" className="text-xs">
                      {duration(p.avg_latency_ms)}
                    </Td>
                    <Td align="right" className="text-xs">
                      {num(p.cost_credits, 2)}
                    </Td>
                  </Tr>
                );
              })}
            </tbody>
          </Table>
        ) : (
          <EmptyState title="No enrichment providers configured" />
        )}
      </Panel>

      <div className="grid gap-4 md:grid-cols-2">
        <Panel title="Routing latency" description="Signal observed → owner assigned">
          <div className="grid grid-cols-3 gap-4">
            <div>
              <div className="text-xs text-muted">Median</div>
              <div className="tabular mt-1 text-base font-semibold">{hours(routing.median_signal_to_owner_hours)}</div>
            </div>
            <div>
              <div className="text-xs text-muted">p90</div>
              <div className="tabular mt-1 text-base font-semibold">{hours(routing.p90_signal_to_owner_hours)}</div>
            </div>
            <div>
              <div className="text-xs text-muted">Decisions</div>
              <div className="tabular mt-1 text-base font-semibold">{num(routing.decisions_with_signal)}</div>
            </div>
          </div>
          <p className="mt-3 text-[11px] text-muted">{routing.note}</p>
        </Panel>

        <Panel title="Runtime" description="How jobs and AI generation run in this environment">
          <dl className="space-y-3 text-xs">
            <div className="flex items-start justify-between gap-3">
              <dt className="text-muted">Job queue</dt>
              <dd className="text-right">
                <span className="font-mono text-text">{queue.backend}</span>{" "}
                {queue.redis_configured ? <Badge tone="success">Redis</Badge> : <Badge>No Redis</Badge>}
                <div className="mt-0.5 text-[11px] text-muted">
                  {queue.backend === "inline"
                    ? "Jobs execute in-process; set a Redis URL to run them on a background worker."
                    : "Jobs are dispatched to a background worker."}
                </div>
              </dd>
            </div>
            <div className="flex items-start justify-between gap-3">
              <dt className="text-muted">LLM</dt>
              <dd className="text-right">
                <span className="font-mono text-text">{llm.mode}</span>{" "}
                {llm.mode === "demo" ? <DemoBadge /> : <Badge tone="success">Live</Badge>}
                <div className="mt-0.5 text-[11px] text-muted">{llm.model ? `Model: ${llm.model}` : "No model configured"}</div>
              </dd>
            </div>
          </dl>
        </Panel>
      </div>
    </div>
  );
}
