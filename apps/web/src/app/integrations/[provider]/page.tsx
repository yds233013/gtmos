import { ArrowLeft, Check, X } from "lucide-react";
import Link from "next/link";
import { notFound } from "next/navigation";

import { ErrorList, EventsTable, SyncsTable } from "@/components/integrations/activity";
import { HealthPill, ModeBadge, RealServiceBadge, VerificationBadge } from "@/components/integrations/labels";
import { duration } from "@/components/systems/format";
import { PageHeader } from "@/components/ui/page-header";
import { Panel } from "@/components/ui/panel";
import { StatCell, StatGrid } from "@/components/ui/stat";
import { ErrorState } from "@/components/ui/states";
import { api, settle } from "@/lib/api";
import { dateTime, num, pct, relTime } from "@/lib/format";
import type { IntegrationActivity, IntegrationStatusResponse } from "@/lib/types";

const PROVIDERS = ["posthog", "clay", "n8n", "hubspot"] as const;

export async function generateMetadata(props: PageProps<"/integrations/[provider]">) {
  const { provider } = await props.params;
  const known = PROVIDERS.find((p) => p === provider);
  return { title: `${known ?? "Integration"} · Integrations` };
}

export default async function IntegrationDetailPage(props: PageProps<"/integrations/[provider]">) {
  const { provider } = await props.params;
  if (!(PROVIDERS as readonly string[]).includes(provider)) notFound();

  const [status, activity] = await settle(
    api<IntegrationStatusResponse>("/integrations/status?days=7"),
    api<IntegrationActivity>(`/integrations/${provider}/activity?days=30&limit=25`),
  );
  const i = status?.integrations.find((x) => x.provider === provider) ?? null;

  if (!i) {
    return (
      <div className="space-y-6">
        <PageHeader title={provider} />
        <ErrorState
          title="Couldn't load this integration"
          message="The GTMOS API did not respond, or this boundary is not instrumented."
        />
      </div>
    );
  }

  const w = i.window;

  return (
    <div className="space-y-6">
      <div>
        <Link href="/integrations" className="inline-flex items-center gap-1 text-xs text-accent-text hover:underline">
          <ArrowLeft className="size-3" aria-hidden />
          All integrations
        </Link>
      </div>

      <PageHeader
        title={i.display_name}
        eyebrow={
          <span className="inline-flex flex-wrap items-center gap-1.5">
            <VerificationBadge level={i.verification} title={i.verification_description} />
            <ModeBadge mode={i.mode} title={i.mode_description} />
            <RealServiceBadge reached={i.reached_real_service} />
            <HealthPill health={i.health} />
          </span>
        }
        description={`${i.summary} ${i.verification_note}`}
      />

      <StatGrid>
        <StatCell label={`Inbound events · ${w.days}d`} value={num(w.inbound_events)} sub={`${num(w.inbound_processed)} processed`} />
        <StatCell label={`Sync runs · ${w.days}d`} value={num(w.syncs)} sub={`${num(w.sync_failures)} failed · ${num(w.sync_partial)} partial`} />
        <StatCell
          label="Error rate"
          value={<span className={(w.error_rate ?? 0) > 0.1 ? "text-warning" : undefined}>{pct(w.error_rate)}</span>}
          sub={`${num(w.error_count)} errors · ${num(w.retry_count)} retries`}
        />
        <StatCell label="Records processed" value={num(w.records_processed)} sub={`${num(w.records_failed)} failed`} />
        <StatCell
          label="Latency"
          value={duration(w.latency.inbound_p50_ms ?? w.latency.sync_p50_ms)}
          sub={
            w.latency.inbound_p50_ms !== null
              ? `inbound p50 · p95 ${duration(w.latency.inbound_p95_ms)}`
              : "sync p50 duration"
          }
        />
        <StatCell
          label="Last inbound event"
          value={relTime(i.last_inbound_event_at)}
          sub={dateTime(i.last_inbound_event_at)}
        />
      </StatGrid>

      <div className="grid gap-4 lg:grid-cols-2">
        <Panel title="What moves, and which way" description="The contract this boundary implements">
          <ul className="space-y-1.5 text-xs text-text">
            {i.moves.map((m) => (
              <li key={m}>{m}</li>
            ))}
          </ul>
          <div className="mt-4 border-t border-border pt-3">
            <h3 className="text-[11px] font-semibold uppercase tracking-wide text-subtle">Endpoints</h3>
            <ul className="mt-1 space-y-0.5">
              {i.endpoints.map((e) => (
                <li key={e} className="break-all font-mono text-[11px] text-muted">
                  {e}
                </li>
              ))}
            </ul>
          </div>
          <div className="mt-4 border-t border-border pt-3">
            <h3 className="text-[11px] font-semibold uppercase tracking-wide text-subtle">Setup docs (in the repo)</h3>
            <ul className="mt-1 space-y-0.5">
              {i.docs.map((d) => (
                <li key={d.path} className="text-[11px] text-muted">
                  {d.label} — <code className="break-all font-mono text-subtle">{d.path}</code>
                </li>
              ))}
            </ul>
          </div>
        </Panel>

        <Panel
          title="What it would take to go live"
          description="Presence only — no secret value is read by this page or returned by the API"
        >
          <ul className="space-y-2">
            {i.requirements.map((r) => (
              <li key={r.key} className="flex items-start gap-2">
                {r.configured ? (
                  <Check className="mt-0.5 size-3.5 shrink-0 text-success" aria-hidden />
                ) : (
                  <X className="mt-0.5 size-3.5 shrink-0 text-muted" aria-hidden />
                )}
                <div className="min-w-0">
                  <p className="break-words text-xs font-medium text-text">
                    {r.key}
                    <span className="ml-1.5 font-normal text-muted">
                      ({r.kind}, {r.configured ? "configured" : "missing"})
                    </span>
                  </p>
                  <p className="break-words text-[11px] text-muted">{r.purpose}</p>
                </div>
              </li>
            ))}
          </ul>
          {i.lifetime.inbound_events > 0 && (
            <p className="mt-4 border-t border-border pt-3 text-[11px] text-muted">
              All time: {num(i.lifetime.inbound_events)} inbound deliveries, of which{" "}
              {num(i.lifetime.real_deliveries)} were really received by this engine and{" "}
              {num(i.lifetime.synthetic_history)} are seeded illustrative history. Non-simulated sync runs:{" "}
              {num(i.lifetime.live_sync_runs)}.
            </p>
          )}
        </Panel>
      </div>

      <Panel
        title="Recent inbound deliveries"
        description={`Last ${activity?.window_days ?? 30} days · signature, dedupe and processing time as recorded`}
        bodyClassName="p-0"
      >
        {activity ? <EventsTable events={activity.events} /> : <ErrorState message="Activity unavailable." />}
      </Panel>

      <Panel title="Recent sync runs" description="Outbound jobs GTMOS ran for this boundary" bodyClassName="p-0">
        {activity ? <SyncsTable syncs={activity.syncs} /> : <ErrorState message="Activity unavailable." />}
      </Panel>

      <Panel title="Recent errors" description="Failed deliveries and failed sync runs, newest first" bodyClassName="p-0">
        {activity ? <ErrorList errors={activity.errors} /> : <ErrorState message="Activity unavailable." />}
      </Panel>
    </div>
  );
}
