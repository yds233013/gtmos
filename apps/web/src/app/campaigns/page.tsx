import { ArrowRight, FlaskConical } from "lucide-react";
import Link from "next/link";

import { ChipLink } from "@/components/insights/chip-link";
import type { BreakdownResponse, Campaign, ExperimentRow } from "@/components/insights/types";
import { Badge, DemoBadge } from "@/components/ui/badge";
import { PageHeader } from "@/components/ui/page-header";
import { Panel } from "@/components/ui/panel";
import { StatCell, StatGrid } from "@/components/ui/stat";
import { EmptyState, ErrorState } from "@/components/ui/states";
import { Table, Td, Th, THead, Tr } from "@/components/ui/table";
import { api, settle } from "@/lib/api";
import { date, money, num, pct, segment, titleCase } from "@/lib/format";
import type { BreakdownRow } from "@/lib/types";
import { cn } from "@/lib/utils";

export const metadata = { title: "Campaigns" };

const DIMENSIONS = [
  { key: "campaign", label: "Campaign" },
  { key: "segment", label: "Segment" },
  { key: "industry", label: "Industry" },
  { key: "region", label: "Region" },
  { key: "score_grade", label: "Score grade" },
  { key: "persona", label: "Persona" },
  { key: "source", label: "Source" },
] as const;

const STATUS_TONE: Record<string, "info" | "neutral" | "warning" | "success" | "danger"> = {
  active: "info",
  running: "info",
  completed: "neutral",
  paused: "warning",
  draft: "neutral",
  archived: "neutral",
};

const OPEN_CAVEAT =
  "Opens are shown for completeness only. Apple Mail Privacy Protection and corporate link scanners pre-fetch tracking pixels, so open counts are inflated and no GTMOS decision uses them.";

function dimensionLabel(dimension: string, key: string): string {
  if (key === "unknown" || key === "") return "Unknown";
  if (dimension === "segment") return segment(key);
  if (dimension === "score_grade") return `Grade ${key}`;
  if (dimension === "persona") return titleCase(key);
  return key;
}

function FunnelStep({
  label,
  value,
  from,
  hint,
}: {
  label: string;
  value: string;
  from?: number | null;
  hint?: string;
}) {
  return (
    <div className="min-w-0 bg-panel px-3 py-2" title={hint}>
      <div className="truncate text-[11px] text-muted">{label}</div>
      <div className="tabular mt-0.5 text-sm font-semibold text-text">{value}</div>
      <div className="tabular h-4 text-[11px] text-subtle">{from !== undefined && from !== null ? `${pct(from, 1)} of prev.` : ""}</div>
    </div>
  );
}

function ratio(a: number, b: number): number | null {
  return b > 0 ? a / b : null;
}

function CampaignCard({ c, experiments }: { c: Campaign; experiments: ExperimentRow[] }) {
  const m = c.metrics;
  const emailed = m.sent > 0;
  const trigger = c.trigger_signal ? titleCase(c.trigger_signal) : null;
  return (
    <article className="rounded-lg border border-border bg-panel">
      <header className="flex flex-col gap-2 border-b border-border px-4 py-3 sm:flex-row sm:items-start sm:justify-between">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <h3 className="text-sm font-semibold text-text">{c.name}</h3>
            <Badge tone={STATUS_TONE[c.status] ?? "neutral"}>{c.status}</Badge>
            {c.data_origin === "demo" && <DemoBadge />}
          </div>
          <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted">
            <span>{titleCase(c.channel)}</span>
            {c.persona && <span>Persona: {c.persona}</span>}
            <span>
              {date(c.start_date)} – {c.end_date ? date(c.end_date) : "ongoing"}
            </span>
          </div>
        </div>
        <div className="flex shrink-0 flex-wrap items-center gap-2">
          {trigger ? (
            <Badge tone="accent" title="The buying signal that enrolls an account">
              Trigger: {trigger}
            </Badge>
          ) : (
            <Badge title="No signal trigger; list- or event-based">No trigger</Badge>
          )}
        </div>
      </header>

      <div className="space-y-3 px-4 py-3">
        {(c.hypothesis || c.value_prop) && (
          <dl className="grid gap-2 text-xs md:grid-cols-2">
            {c.hypothesis && (
              <div>
                <dt className="text-[11px] font-medium uppercase tracking-wide text-muted">Hypothesis</dt>
                <dd className="mt-0.5 text-text">{c.hypothesis}</dd>
              </div>
            )}
            {c.value_prop && (
              <div>
                <dt className="text-[11px] font-medium uppercase tracking-wide text-muted">Value proposition</dt>
                <dd className="mt-0.5 text-text">{c.value_prop}</dd>
              </div>
            )}
          </dl>
        )}

        <div
          className="grid grid-cols-2 gap-px overflow-hidden rounded-md border border-border bg-border sm:grid-cols-4 xl:grid-cols-8"
          aria-label={`${c.name} funnel`}
        >
          <FunnelStep label="Accounts touched" value={num(m.accounts_touched)} />
          <FunnelStep label="Sent" value={emailed ? num(m.sent) : "—"} hint={emailed ? `${num(m.delivered)} delivered, ${num(m.bounced)} bounced` : "No email sends"} />
          <FunnelStep label="Replied" value={emailed ? num(m.replied) : "—"} from={emailed ? ratio(m.replied, m.delivered || m.sent) : null} />
          <FunnelStep label="Positive replies" value={emailed ? num(m.positive_replies) : "—"} from={emailed ? ratio(m.positive_replies, m.replied) : null} />
          <FunnelStep
            label="Meetings"
            value={num(m.meetings)}
            from={emailed ? ratio(m.meetings, m.positive_replies) : ratio(m.meetings, m.accounts_touched)}
          />
          <FunnelStep label="Opportunities" value={num(m.opportunities)} from={ratio(m.opportunities, m.meetings)} />
          <FunnelStep label="Pipeline" value={money(m.pipeline)} />
          <FunnelStep label="Won" value={`${num(m.won)} · ${money(m.won_revenue)}`} from={ratio(m.won, m.opportunities)} />
        </div>

        <div className="flex flex-wrap items-center justify-between gap-3 text-xs">
          <div className="flex flex-wrap items-center gap-x-4 gap-y-1">
            <span className="text-muted">
              Reply rate <span className="tabular font-medium text-text">{emailed ? pct(m.reply_rate) : "—"}</span>
            </span>
            <span className="text-muted">
              Positive reply rate <span className="tabular font-medium text-text">{emailed ? pct(m.positive_reply_rate) : "—"}</span>
            </span>
            <span className="text-muted">
              Meetings / account{" "}
              <span className="tabular font-medium text-text">{pct(ratio(m.meetings, m.accounts_touched))}</span>
            </span>
            {emailed && (
              <span className="text-subtle" title={OPEN_CAVEAT}>
                Opened {num(m.opened)} (unreliable<sup>*</sup>)
              </span>
            )}
          </div>
          {experiments.length > 0 && (
            <div className="flex flex-wrap gap-2">
              {experiments.map((e) => (
                <Link
                  key={e.key}
                  href={`/experiments/${e.key}`}
                  className="inline-flex items-center gap-1 text-accent-text hover:underline"
                >
                  <FlaskConical className="size-3.5" aria-hidden />
                  Experiment: {e.name}
                  <ArrowRight className="size-3" aria-hidden />
                </Link>
              ))}
            </div>
          )}
        </div>
      </div>
    </article>
  );
}

function RateCell({ value, max, muted }: { value: number; max: number; muted: boolean }) {
  return (
    <div className="flex items-center justify-end gap-2">
      <div className="hidden h-1.5 w-20 overflow-hidden rounded-full bg-panel-2 sm:block" aria-hidden>
        <div className={cn("h-full rounded-full", muted ? "bg-subtle" : "bg-accent")} style={{ width: `${max > 0 ? (value / max) * 100 : 0}%` }} />
      </div>
      <span className={cn("tabular w-12 text-right", muted ? "text-muted" : "font-medium text-text")}>{pct(value)}</span>
    </div>
  );
}

function BreakdownTable({ data }: { data: BreakdownResponse }) {
  const rows: BreakdownRow[] = [...data.rows].sort(
    (a, b) => Number(a.low_sample) - Number(b.low_sample) || b.meeting_rate - a.meeting_rate,
  );
  const maxMeeting = Math.max(...rows.map((r) => r.meeting_rate), 0);
  const maxOpp = Math.max(...rows.map((r) => r.opportunity_rate), 0);
  if (!rows.length) return <EmptyState title="No contacted accounts in this window" />;
  return (
    <Table>
      <THead>
        <tr>
          <Th>{DIMENSIONS.find((d) => d.key === data.dimension)?.label ?? titleCase(data.dimension)}</Th>
          <Th align="right">Contacted</Th>
          <Th align="right">Meetings</Th>
          <Th align="right">Meeting rate</Th>
          <Th align="right">Opps</Th>
          <Th align="right">Opp rate</Th>
          <Th align="right">Pipeline</Th>
          <Th align="right">Won</Th>
        </tr>
      </THead>
      <tbody>
        {rows.map((r) => (
          <Tr key={r.key} className={r.low_sample ? "text-muted" : undefined}>
            <Td className="max-w-72">
              <div className="flex flex-wrap items-center gap-1.5">
                <span className={cn("truncate", r.low_sample ? "text-muted" : "font-medium")}>{dimensionLabel(data.dimension, r.key)}</span>
                {r.low_sample && (
                  <Badge tone="warning" title="Too few contacted accounts to rank reliably">
                    Small sample
                  </Badge>
                )}
              </div>
            </Td>
            <Td align="right">{num(r.contacted)}</Td>
            <Td align="right">{num(r.meetings)}</Td>
            <Td align="right">
              <RateCell value={r.meeting_rate} max={maxMeeting} muted={r.low_sample} />
            </Td>
            <Td align="right">{num(r.opportunities)}</Td>
            <Td align="right">
              <RateCell value={r.opportunity_rate} max={maxOpp} muted={r.low_sample} />
            </Td>
            <Td align="right">{money(r.pipeline)}</Td>
            <Td align="right">{num(r.won)}</Td>
          </Tr>
        ))}
      </tbody>
    </Table>
  );
}

export default async function CampaignsPage(props: PageProps<"/campaigns">) {
  const sp = await props.searchParams;
  const rawDim = typeof sp.dimension === "string" ? sp.dimension : "campaign";
  const dimension = DIMENSIONS.some((d) => d.key === rawDim) ? rawDim : "campaign";

  const [campaigns, experiments, breakdown] = await settle(
    api<Campaign[]>("/campaigns"),
    api<ExperimentRow[]>("/experiments"),
    api<BreakdownResponse>(`/analytics/breakdown?dimension=${encodeURIComponent(dimension)}&days=180`),
  );

  const header = (
    <PageHeader
      title="Campaigns"
      eyebrow={<DemoBadge />}
      description="Each campaign is a hypothesis: a trigger, a persona and a value proposition. Judge them on replies, meetings and pipeline, never on opens."
    />
  );

  if (!campaigns) {
    return (
      <div>
        {header}
        <ErrorState title="Couldn't load campaigns" message="The campaigns endpoint failed. Check that the API is running." />
      </div>
    );
  }

  const order: Record<string, number> = { active: 0, running: 0, paused: 1, completed: 2 };
  const sorted = [...campaigns].sort((a, b) => (order[a.status] ?? 3) - (order[b.status] ?? 3) || b.metrics.pipeline - a.metrics.pipeline);
  const totals = campaigns.reduce(
    (acc, c) => ({
      sent: acc.sent + c.metrics.sent,
      delivered: acc.delivered + c.metrics.delivered,
      replied: acc.replied + c.metrics.replied,
      meetings: acc.meetings + c.metrics.meetings,
      opportunities: acc.opportunities + c.metrics.opportunities,
      pipeline: acc.pipeline + c.metrics.pipeline,
      won_revenue: acc.won_revenue + c.metrics.won_revenue,
      won: acc.won + c.metrics.won,
    }),
    { sent: 0, delivered: 0, replied: 0, meetings: 0, opportunities: 0, pipeline: 0, won_revenue: 0, won: 0 },
  );
  const active = campaigns.filter((c) => c.status === "active" || c.status === "running").length;
  const expsByCampaign = (name: string) => (experiments ?? []).filter((e) => e.campaign === name);

  return (
    <div className="space-y-6">
      {header}

      <StatGrid>
        <StatCell label="Campaigns" value={num(campaigns.length)} sub={`${num(active)} active`} />
        <StatCell label="Emails sent" value={num(totals.sent)} sub={`${num(totals.delivered)} delivered`} />
        <StatCell label="Replies" value={num(totals.replied)} sub={`${pct(ratio(totals.replied, totals.delivered))} of delivered`} />
        <StatCell label="Meetings" value={num(totals.meetings)} sub={`${num(totals.opportunities)} opportunities`} />
        <StatCell label="Pipeline sourced" value={money(totals.pipeline)} />
        <StatCell label="Won revenue" value={money(totals.won_revenue)} sub={`${num(totals.won)} deals`} />
      </StatGrid>

      <section aria-labelledby="campaigns-heading" className="space-y-3">
        <div className="flex flex-wrap items-baseline justify-between gap-2">
          <h2 id="campaigns-heading" className="text-sm font-semibold text-text">
            All campaigns
          </h2>
          <Link href="/experiments" className="text-xs text-accent-text hover:underline">
            View experiments
          </Link>
        </div>
        {sorted.length ? (
          <div className="space-y-3">
            {sorted.map((c) => (
              <CampaignCard key={c.id} c={c} experiments={expsByCampaign(c.name)} />
            ))}
          </div>
        ) : (
          <Panel>
            <EmptyState title="No campaigns yet" description="Campaigns appear here once they are created in GTMOS or synced from the CRM." />
          </Panel>
        )}
        <p className="text-[11px] text-muted">
          <sup>*</sup> {OPEN_CAVEAT}
        </p>
      </section>

      <Panel
        id="breakdown"
        title="Conversion breakdown"
        description="Contacted accounts in the last 180 days · meeting and opportunity rates · small samples are flagged and ranked last"
        bodyClassName="p-0"
      >
        <nav aria-label="Breakdown dimension" className="flex flex-wrap gap-1.5 border-b border-border px-4 py-3">
          {DIMENSIONS.map((d) => (
            <ChipLink key={d.key} href={`/campaigns?dimension=${d.key}#breakdown`} active={d.key === dimension}>
              {d.label}
            </ChipLink>
          ))}
        </nav>
        {breakdown ? (
          <BreakdownTable data={breakdown} />
        ) : (
          <div className="p-4">
            <ErrorState title="Couldn't load the breakdown" message={`The ${dimension} breakdown failed to load.`} />
          </div>
        )}
      </Panel>
    </div>
  );
}
