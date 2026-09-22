import { Info } from "lucide-react";
import Link from "next/link";

import { BarTrend } from "@/components/charts/bar-trend";
import { oneOf } from "@/components/revenue/query";
import { Badge, DemoBadge, GradeBadge } from "@/components/ui/badge";
import { PageHeader } from "@/components/ui/page-header";
import { Panel } from "@/components/ui/panel";
import { StatCell, StatGrid } from "@/components/ui/stat";
import { EmptyState, ErrorState } from "@/components/ui/states";
import { Table, Td, Th, THead, Tr } from "@/components/ui/table";
import { api, settle } from "@/lib/api";
import { date, money, num, pct, titleCase } from "@/lib/format";
import type { Funnel, PipelineTrend } from "@/lib/types";
import { cn } from "@/lib/utils";

import type { Attribution, AttributionModel, OpportunityList, OwnerLoad, Stuck, Velocity } from "./types";

export const metadata = { title: "Pipeline" };

const OPEN_STAGES = ["discovery", "evaluation", "proposal", "negotiation"] as const;
const MODEL_LABEL: Record<AttributionModel, string> = {
  first_touch: "First touch",
  last_touch: "Last touch",
  linear: "Linear",
  u_shaped: "U-shaped",
};
/** Stage transitions observed for fewer accounts than this are flagged as small samples. */
const MIN_SAMPLE = 10;
const DAY = 86_400_000;

function daysSince(iso: string, now: number = Date.now()): number {
  return Math.max(0, Math.floor((now - new Date(iso).getTime()) / DAY));
}

function isOverdue(isoDate: string | null, now: number = Date.now()): boolean {
  return Boolean(isoDate) && new Date(`${isoDate}T23:59:59Z`).getTime() < now;
}

function withinDays(iso: string | null, days: number, now: number = Date.now()): boolean {
  return Boolean(iso) && now - new Date(iso as string).getTime() <= days * DAY;
}

export default async function PipelinePage(props: PageProps<"/pipeline">) {
  const sp = await props.searchParams;
  const attrView = oneOf(sp.attr, ["pipeline", "won"] as const) ?? "pipeline";

  const [opps, velocity, attribution, stuck, users, trend, funnel] = await settle(
    api<OpportunityList>("/opportunities"),
    api<Velocity>("/analytics/velocity?days=180"),
    api<Attribution>("/analytics/attribution?days=180"),
    api<Stuck>("/analytics/stuck"),
    api<OwnerLoad[]>("/users"),
    api<PipelineTrend>("/analytics/pipeline-trend?weeks=16"),
    api<Funnel>("/analytics/funnel?days=90"),
  );

  if (!opps && !velocity) {
    return (
      <div>
        <PageHeader title="Pipeline" description="Open deals, conversion velocity, attribution and stuck accounts." />
        <ErrorState title="The GTMOS API is unavailable" message="Start the backend with `make dev`, then reload." />
      </div>
    );
  }

  const items = opps?.items ?? [];
  const open = items.filter((o) => (OPEN_STAGES as readonly string[]).includes(o.stage));
  const openPipeline = open.reduce((s, o) => s + o.amount_usd, 0);
  const closed180 = items.filter((o) => o.closed_at && withinDays(o.closed_at, 180));
  const won180 = closed180.filter((o) => o.stage === "closed_won");
  const lost180 = closed180.filter((o) => o.stage === "closed_lost");
  const lostReasons = Object.entries(
    lost180.reduce<Record<string, number>>((acc, o) => {
      const k = o.lost_reason ?? "No reason recorded";
      acc[k] = (acc[k] ?? 0) + 1;
      return acc;
    }, {}),
  ).sort((a, b) => b[1] - a[1]);
  const hasDemo = items.some((o) => o.data_origin === "demo");
  const ownerName = new Map((users ?? []).map((u) => [u.user_id, u.name]));
  const v = velocity;

  const board = OPEN_STAGES.map((stage) => {
    const deals = open.filter((o) => o.stage === stage).sort((a, b) => b.amount_usd - a.amount_usd);
    return { stage, deals, total: deals.reduce((s, o) => s + o.amount_usd, 0) };
  });

  const weeks = trend?.weeks ?? [];

  return (
    <div className="space-y-6">
      <PageHeader
        title="Pipeline"
        eyebrow={
          <span className="inline-flex items-center gap-2">
            {num(open.length)} open deals · win rate and cycle over 180 days {hasDemo && <DemoBadge />}
          </span>
        }
        description="Where open deals sit, how fast they move, which campaigns get credit under each attribution model, and which accounts have stalled. Every number is computed live from opportunities and stage history."
      />

      <div className="space-y-2">
        <StatGrid>
          <StatCell label="Open pipeline" value={money(openPipeline)} sub={`${num(open.length)} open deals`} />
          <StatCell
            label="Win rate"
            value={v ? pct(v.win_rate, 0) : "—"}
            sub={
              v ? (
                <span className="inline-flex items-center gap-1.5">
                  {num(v.closed_deals)} closed deals {v.low_sample && <Badge tone="warning">Small sample</Badge>}
                </span>
              ) : undefined
            }
          />
          <StatCell label="Avg won deal" value={v ? money(v.avg_won_deal) : "—"} sub="Closed-won, 180 days" />
          <StatCell
            label="Median sales cycle"
            value={v?.median_cycle_days != null ? `${num(v.median_cycle_days, 1)}d` : "—"}
            sub="Opened → closed"
          />
          <StatCell label="Open opportunities" value={v ? num(v.open_opportunities) : "—"} sub="Used in velocity" />
          <StatCell
            label="Pipeline velocity"
            value={v ? `${money(v.pipeline_velocity_per_day)}/day` : "—"}
            sub="Expected revenue per day"
            hint={v ? `Velocity = ${v.formula}` : undefined}
          />
        </StatGrid>
        {v && (
          <p className="flex items-start gap-1.5 text-[11px] text-muted">
            <Info className="mt-px size-3 shrink-0" aria-hidden />
            <span>
              Velocity = {v.formula} = {num(v.open_opportunities)} × {pct(v.win_rate, 1)} × {money(v.avg_won_deal)} ÷{" "}
              {num(v.median_cycle_days, 1)}d = <span className="tabular font-medium text-text">{money(v.pipeline_velocity_per_day)}/day</span>.
              {v.low_sample && " Fewer closed deals than needed for a stable estimate; treat as directional."}
            </span>
          </p>
        )}
      </div>

      <Panel
        title="Open deals by stage"
        description="Read-only board · sorted by amount · age = days since the opportunity opened"
        bodyClassName="p-0"
      >
        {open.length === 0 ? (
          <EmptyState title="No open deals" description="Opportunities appear here once an account converts from a meeting." />
        ) : (
          <div className="overflow-x-auto">
            <div className="grid min-w-[880px] grid-cols-4 divide-x divide-border">
              {board.map((col) => (
                <section key={col.stage} aria-label={`${titleCase(col.stage)} deals`} className="min-w-0">
                  <header className="flex items-baseline justify-between gap-2 border-b border-border bg-panel-2/60 px-3 py-2">
                    <h3 className="text-xs font-semibold text-text">
                      {titleCase(col.stage)} <span className="tabular font-normal text-muted">{num(col.deals.length)}</span>
                    </h3>
                    <span className="tabular text-xs text-muted">{money(col.total)}</span>
                  </header>
                  <ul className="max-h-[32rem] space-y-2 overflow-y-auto p-2">
                    {col.deals.length === 0 && <li className="px-1 py-4 text-center text-xs text-subtle">No deals</li>}
                    {col.deals.map((o) => {
                      const overdue = isOverdue(o.expected_close_date);
                      return (
                        <li key={o.id} className="rounded-md border border-border bg-panel p-2.5 text-xs">
                          <div className="flex items-start justify-between gap-2">
                            <Link href={`/accounts/${o.account_id}`} className="min-w-0 truncate font-medium text-text hover:underline">
                              {o.account_name ?? "Unknown account"}
                            </Link>
                            <span className="tabular shrink-0 font-semibold text-text">{money(o.amount_usd)}</span>
                          </div>
                          <div className="mt-0.5 truncate text-[11px] text-muted" title={o.name}>
                            {o.name}
                          </div>
                          <div className="mt-2 flex flex-wrap items-center gap-1.5">
                            <GradeBadge grade={o.account_grade} />
                            <span className="text-[11px] text-muted">{daysSince(o.opened_at)}d old</span>
                            <span className="text-[11px] text-subtle" aria-hidden>
                              ·
                            </span>
                            {o.owner ? (
                              <span className="truncate text-[11px] text-muted">{o.owner}</span>
                            ) : (
                              <span className="text-[11px] font-medium text-warning">Unowned</span>
                            )}
                          </div>
                          {o.expected_close_date && (
                            <div className={cn("mt-1 text-[11px]", overdue ? "font-medium text-danger" : "text-muted")}>
                              {overdue ? "Close date passed: " : "Expected close "}
                              {date(o.expected_close_date)}
                            </div>
                          )}
                        </li>
                      );
                    })}
                  </ul>
                </section>
              ))}
            </div>
          </div>
        )}
      </Panel>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
        <Panel
          title="Cohort funnel and time between stages"
          description={
            funnel
              ? `${num(funnel.cohort_size)} accounts first contacted in 90 days · median days from the previous stage (180 days)`
              : "Median days from the previous stage (180 days)"
          }
          className="lg:col-span-2"
          bodyClassName="p-0"
        >
          {funnel || v ? (
            <Table>
              <THead>
                <tr>
                  <Th>Stage</Th>
                  <Th align="right">Reached</Th>
                  <Th align="right">Step conversion</Th>
                  <Th align="right">Of cohort</Th>
                  <Th align="right">Median days from previous · 180d</Th>
                  <Th align="right">Transitions measured</Th>
                </tr>
              </THead>
              <tbody>
                {(funnel?.stages ?? v?.stage_durations.map((d) => ({ stage: d.to, accounts: 0, conversion_from_previous: null })) ?? []).map((s) => {
                  const dur = v?.stage_durations.find((d) => d.to === s.stage);
                  const small = dur ? dur.accounts < MIN_SAMPLE : false;
                  return (
                    <Tr key={s.stage}>
                      <Td className="whitespace-nowrap text-xs font-medium">{titleCase(s.stage)}</Td>
                      <Td align="right" className="text-xs">
                        {funnel ? num(s.accounts) : "—"}
                      </Td>
                      <Td align="right" className="text-xs text-muted">
                        {s.conversion_from_previous === null ? "—" : pct(s.conversion_from_previous, 0)}
                      </Td>
                      <Td align="right" className="text-xs text-subtle">
                        {"conversion_from_cohort" in s && s.conversion_from_cohort != null
                          ? pct(s.conversion_from_cohort, 0)
                          : "—"}
                      </Td>
                      <Td align="right" className="text-xs">
                        {dur ? (
                          <span className="inline-flex items-center gap-1.5">
                            {small && <Badge tone="warning">Small sample</Badge>}
                            <span className={cn(small && "text-muted")}>
                              {dur.median_days === null ? "—" : `${num(dur.median_days, 1)}d`}
                            </span>
                          </span>
                        ) : (
                          <span className="text-subtle">—</span>
                        )}
                      </Td>
                      <Td align="right" className="text-xs text-muted">
                        {dur ? `${num(dur.accounts)} (${titleCase(dur.from)} → ${titleCase(dur.to)})` : "—"}
                      </Td>
                    </Tr>
                  );
                })}
              </tbody>
            </Table>
          ) : (
            <p className="p-4 text-xs text-muted">Funnel and velocity data are unavailable.</p>
          )}
          <p className="border-t border-border px-4 py-2.5 text-[11px] text-muted">
            {funnel?.cohort_definition ?? ""} Account funnel stages, not deal stages. Medians with fewer than{" "}
            {MIN_SAMPLE} measured transitions are marked as small samples.
            {funnel ? ` ${num(funnel.lost)} accounts were marked lost in the last 90 days.` : ""}
          </p>
        </Panel>

        <Panel title="Closed in the last 180 days" description="From opportunity records">
          <dl className="grid grid-cols-2 gap-3">
            <div>
              <dt className="text-xs text-muted">Won</dt>
              <dd className="tabular mt-1 text-base font-semibold text-success">{money(won180.reduce((s, o) => s + o.amount_usd, 0))}</dd>
              <dd className="text-[11px] text-muted">{num(won180.length)} deals</dd>
            </div>
            <div>
              <dt className="text-xs text-muted">Lost</dt>
              <dd className="tabular mt-1 text-base font-semibold text-danger">{money(lost180.reduce((s, o) => s + o.amount_usd, 0))}</dd>
              <dd className="text-[11px] text-muted">{num(lost180.length)} deals</dd>
            </div>
          </dl>
          <h3 className="mt-4 text-[11px] font-medium uppercase tracking-wide text-muted">Lost reasons</h3>
          {lostReasons.length ? (
            <ul className="mt-1.5 space-y-1">
              {lostReasons.map(([reason, n]) => (
                <li key={reason} className="flex items-center justify-between gap-2 text-xs">
                  <span className="truncate text-text">{titleCase(reason)}</span>
                  <span className="tabular shrink-0 text-muted">{num(n)}</span>
                </li>
              ))}
            </ul>
          ) : (
            <p className="mt-1.5 text-xs text-muted">No lost deals in this window.</p>
          )}
          {lost180.length + won180.length < 20 && (
            <p className="mt-3 text-[11px] text-warning">Small sample: fewer than 20 closed deals.</p>
          )}
        </Panel>
      </div>

      <Panel title="Pipeline created by week" description="Opportunity amount at creation · last 16 weeks">
        {weeks.length ? (
          <BarTrend
            data={weeks.map((w) => ({
              label: new Date(w.week).toLocaleDateString("en-US", { month: "short", day: "numeric", timeZone: "UTC" }),
              value: w.pipeline,
            }))}
            valueFormat="money"
            seriesLabel="Pipeline created"
            height={180}
          />
        ) : (
          <p className="text-xs text-muted">No pipeline created in this window.</p>
        )}
        {trend?.note && <p className="mt-2 text-[11px] text-muted">{trend.note}</p>}
      </Panel>

      <AttributionPanel attribution={attribution} view={attrView} />

      <StuckPanel stuck={stuck} ownerName={ownerName} />
    </div>
  );
}

function AttributionPanel({ attribution: a, view }: { attribution: Attribution | null; view: "pipeline" | "won" }) {
  if (!a) {
    return (
      <Panel title="Attribution">
        <ErrorState title="Attribution is unavailable" />
      </Panel>
    );
  }
  const models = a.models;
  const valueOf = (r: Attribution["rows"][number], m: AttributionModel): number =>
    view === "won" ? (r[`${m}_won` as keyof typeof r] as number | undefined) ?? 0 : r[m];
  const totals = Object.fromEntries(models.map((m) => [m, a.rows.reduce((s, r) => s + valueOf(r, m), 0)])) as Record<AttributionModel, number>;
  const unattributedShare = a.total_pipeline > 0 ? a.unattributed_pipeline / a.total_pipeline : 0;

  return (
    <Panel
      title="Campaign attribution"
      description={`Four models side by side · ${num(a.opportunities)} opportunities, ${money(a.total_pipeline)} pipeline · ${a.window_days} days`}
      actions={
        <div role="group" aria-label="Attribution measure" className="inline-flex rounded-md border border-border p-0.5">
          {(["pipeline", "won"] as const).map((k) => (
            <Link
              key={k}
              href={k === "pipeline" ? "/pipeline" : "/pipeline?attr=won"}
              scroll={false}
              aria-current={view === k ? "page" : undefined}
              className={cn(
                "rounded px-2 py-0.5 text-xs font-medium",
                view === k ? "bg-accent-soft text-accent-text" : "text-muted hover:bg-panel-2 hover:text-text",
              )}
            >
              {k === "pipeline" ? "Pipeline" : "Won revenue"}
            </Link>
          ))}
        </div>
      }
      bodyClassName="p-0"
    >
      {a.rows.length === 0 ? (
        <EmptyState title="No attributed opportunities" description="Attribution needs opportunities with recorded campaign touches." />
      ) : (
        <Table>
          <THead>
            <tr>
              <Th>Campaign</Th>
              {models.map((m) => (
                <Th key={m} align="right">
                  {MODEL_LABEL[m] ?? titleCase(m)}
                </Th>
              ))}
              <Th align="right" className="whitespace-nowrap">
                Model spread
              </Th>
            </tr>
          </THead>
          <tbody>
            {a.rows.map((r) => {
              const vals = models.map((m) => valueOf(r, m));
              const hi = Math.max(...vals);
              const lo = Math.min(...vals);
              const spread = hi > 0 ? (hi - lo) / hi : 0;
              return (
                <Tr key={r.key}>
                  <Td className="min-w-56 text-xs font-medium">{r.key}</Td>
                  {models.map((m, i) => (
                    <Td key={m} align="right" className="text-xs">
                      <div className={cn(vals[i] === hi && spread > 0 && "font-semibold")}>{money(vals[i])}</div>
                      <div className="text-[11px] text-muted">{totals[m] > 0 ? pct(vals[i] / totals[m], 0) : "—"}</div>
                    </Td>
                  ))}
                  <Td align="right" className="text-xs">
                    {spread >= 0.2 ? (
                      <Badge tone="warning" title="Models disagree by 20% or more: credit depends on the model you pick">
                        {pct(spread, 0)}
                      </Badge>
                    ) : (
                      <span className="text-muted">{pct(spread, 0)}</span>
                    )}
                  </Td>
                </Tr>
              );
            })}
            <tr className="border-t border-border bg-panel-2/60">
              <Td className="text-xs font-semibold">Total attributed</Td>
              {models.map((m) => (
                <Td key={m} align="right" className="text-xs font-semibold">
                  {money(totals[m])}
                </Td>
              ))}
              <Td />
            </tr>
          </tbody>
        </Table>
      )}
      <div className="grid gap-4 border-t border-border px-4 py-3 md:grid-cols-3">
        <div className="text-xs">
          <div className="text-muted">Unattributed</div>
          <div className="tabular mt-1 text-base font-semibold text-text">{pct(unattributedShare, 0)}</div>
          <div className="text-[11px] text-muted">
            {num(a.unattributed_opportunities)} opportunities · {money(a.unattributed_pipeline)} with no recorded campaign touch
          </div>
          <p className="mt-2 text-[11px] text-muted">
            Share is the percent of each model&apos;s credited total. Spread = (highest − lowest) ÷ highest across models.
          </p>
        </div>
        <div className="md:col-span-2">
          <h3 className="text-xs font-medium text-text">Limitations</h3>
          <ul className="mt-1.5 list-disc space-y-1 pl-4 text-[11px] text-muted">
            {a.limitations.map((l) => (
              <li key={l}>{l}</li>
            ))}
          </ul>
        </div>
      </div>
    </Panel>
  );
}

function StuckPanel({ stuck, ownerName }: { stuck: Stuck | null; ownerName: Map<string, string> }) {
  if (!stuck) {
    return (
      <Panel title="Stuck accounts">
        <ErrorState title="Stuck-account analysis is unavailable" />
      </Panel>
    );
  }
  const stages = Object.entries(stuck.by_stage).sort((a, b) => b[1] - a[1]);
  return (
    <Panel
      title="Stuck accounts"
      description={`${num(stuck.total)} accounts past their stage's time limit · showing the ${num(stuck.accounts.length)} with the highest ICP score`}
      actions={
        <Link href="/stack-inspector" className="text-xs text-accent-text hover:underline">
          Stack Inspector
        </Link>
      }
      bodyClassName="p-0"
    >
      {stages.length > 0 && (
        <ul className="flex flex-wrap gap-1.5 border-b border-border px-4 py-3" aria-label="Stuck accounts by stage">
          {stages.map(([stage, n]) => (
            <li key={stage} className="inline-flex items-center gap-1.5 rounded-md border border-border px-2 py-1 text-xs">
              <span className="text-text">{titleCase(stage)}</span>
              <span className="tabular font-medium text-text">{num(n)}</span>
              {stuck.unowned_by_stage[stage] ? (
                <span className="text-[11px] text-warning">{num(stuck.unowned_by_stage[stage])} unowned</span>
              ) : null}
            </li>
          ))}
        </ul>
      )}
      {stuck.accounts.length === 0 ? (
        <EmptyState title="Nothing is stuck" description="Every account is moving within its stage's time limit." />
      ) : (
        <Table>
          <THead>
            <tr>
              <Th>Account</Th>
              <Th>Stage</Th>
              <Th align="right">Days in stage</Th>
              <Th>Rule triggered</Th>
              <Th>Owner</Th>
              <Th>Region</Th>
              <Th align="right">ICP</Th>
            </tr>
          </THead>
          <tbody>
            {stuck.accounts.map((s) => (
              <Tr key={s.account_id}>
                <Td className="whitespace-nowrap">
                  <Link href={`/accounts/${s.account_id}`} className="font-medium hover:underline">
                    {s.name}
                  </Link>
                </Td>
                <Td className="whitespace-nowrap text-xs">{titleCase(s.stage)}</Td>
                <Td align="right" className={cn("text-xs", s.days_in_stage >= 60 && "font-medium text-danger")}>
                  {num(s.days_in_stage)}
                </Td>
                <Td className="min-w-56 text-xs text-muted">{s.rule}</Td>
                <Td className="whitespace-nowrap text-xs">
                  {s.owner_id ? (
                    (ownerName.get(s.owner_id) ?? <span className="font-mono text-[11px] text-muted">{s.owner_id.slice(0, 8)}</span>)
                  ) : (
                    <span className="font-medium text-warning">Unowned</span>
                  )}
                </Td>
                <Td className="text-xs">{s.region ?? "—"}</Td>
                <Td align="right" className="text-xs">
                  {s.icp_score ?? "—"}
                </Td>
              </Tr>
            ))}
          </tbody>
        </Table>
      )}
    </Panel>
  );
}
