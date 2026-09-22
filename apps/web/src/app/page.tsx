import { ArrowRight } from "lucide-react";
import Link from "next/link";

import { BarTrend } from "@/components/charts/bar-trend";
import { FunnelBars } from "@/components/charts/funnel";
import { HBarList } from "@/components/charts/hbar-list";
import { DemoBadge, GradeBadge, StatusBadge, StatusDot } from "@/components/ui/badge";
import { PageHeader } from "@/components/ui/page-header";
import { Panel } from "@/components/ui/panel";
import { StatCell, StatGrid } from "@/components/ui/stat";
import { ErrorState } from "@/components/ui/states";
import { Table, Td, Th, THead, Tr } from "@/components/ui/table";
import { api, settle } from "@/lib/api";
import { money, num, pct, relTime, titleCase } from "@/lib/format";
import type { AccountRow, Breakdown, Funnel, Inspector, Overview, Paged, PipelineTrend, Signal, Workspace } from "@/lib/types";

export const metadata = { title: "Overview" };

const DEMO_PATH: { href: (ws: Workspace | null) => string; label: string }[] = [
  { href: (ws) => (ws?.flagship_account_id ? `/accounts/${ws.flagship_account_id}` : "/accounts"), label: "Open the flagship account (Kestrel Analytics)" },
  { href: () => "/approvals", label: "Review AI drafts in the approval queue" },
  { href: () => "/workflows", label: "Inspect workflow runs, retries and dead letters" },
  { href: () => "/stack-inspector", label: "Run the GTM Stack Inspector" },
  { href: () => "/copilot", label: "Ask the Copilot why pipeline changed" },
];

export default async function OverviewPage() {
  const [ws, overview, funnel, trend, top, signals, inspector, grades] = await settle(
    api<Workspace>("/workspace"),
    api<Overview>("/analytics/overview?days=90"),
    api<Funnel>("/analytics/funnel?days=90"),
    api<PipelineTrend>("/analytics/pipeline-trend?weeks=16"),
    api<Paged<AccountRow>>("/accounts?grade=A&grade=B&sort=intent&customers=exclude&page_size=8"),
    api<Paged<Signal>>("/signals?days=14&page_size=6&min_confidence=0.8"),
    api<Inspector>("/stack-inspector"),
    api<{ rows: Breakdown["rows"]; note: string }>("/analytics/score-validation"),
  );

  if (!overview) {
    return <ErrorState title="The GTMOS API is unavailable" message="Start the backend with `make dev`, then reload." />;
  }
  const o = overview;
  const weeks = trend?.weeks ?? [];

  return (
    <div className="space-y-6">
      <PageHeader
        title="Command center"
        eyebrow={
          <span className="inline-flex items-center gap-2">
            {ws?.seller_name ?? "GTMOS"} · last {o.window_days} days <DemoBadge />
          </span>
        }
        description="Which accounts to target, why now, what to say, and whether the go-to-market machine is healthy. Every number below is computed live from the GTMOS database."
      />

      <StatGrid>
        <StatCell label="Accounts in universe" value={num(o.accounts_sourced)} sub={`${pct(o.enrichment_coverage, 0)} fully enriched`} />
        <StatCell label="ICP accounts (A/B)" value={num(o.icp_accounts)} sub={`${num(o.high_intent_accounts)} high intent`} />
        <StatCell label="Meetings" value={num(o.meetings)} sub={`${num(o.qualified_accounts)} accounts qualified`} />
        <StatCell label="Pipeline created" value={money(o.pipeline_created)} sub={`${num(o.opportunities_created)} opportunities`} />
        <StatCell label="Open pipeline" value={money(o.open_pipeline)} sub={`${num(o.open_opportunities)} open deals`} />
        <StatCell label="Won revenue" value={money(o.won_revenue)} sub={`${num(o.won_deals)} deals`} />
      </StatGrid>

      <div className="grid gap-4 lg:grid-cols-3">
        <Panel title="Pipeline created by week" description="Opportunity amount at creation · last 16 weeks" className="lg:col-span-2">
          {weeks.length ? (
            <BarTrend
              data={weeks.map((w) => ({ label: new Date(w.week).toLocaleDateString("en-US", { month: "short", day: "numeric" }), value: w.pipeline }))}
              valueFormat="money"
              seriesLabel="Pipeline created"
              height={200}
            />
          ) : (
            <p className="text-xs text-muted">No pipeline data.</p>
          )}
          <p className="mt-2 text-[11px] text-muted">{trend?.note}</p>
        </Panel>
        <Panel title="Funnel" description="Accounts reaching each stage · 90 days">
          {funnel ? <FunnelBars stages={funnel.stages} /> : <p className="text-xs text-muted">Unavailable.</p>}
        </Panel>
      </div>

      <div className="grid gap-4 lg:grid-cols-3">
        <Panel
          title="Act now"
          description="Highest-intent A/B accounts that are not customers"
          className="lg:col-span-2"
          bodyClassName="p-0"
          actions={
            <Link href="/accounts?grade=A&grade=B&sort=intent" className="text-xs text-accent-text hover:underline">
              All accounts
            </Link>
          }
        >
          <Table>
            <THead>
              <tr>
                <Th>Account</Th>
                <Th>Score</Th>
                <Th align="right">Intent</Th>
                <Th>Latest signal</Th>
                <Th>Owner</Th>
              </tr>
            </THead>
            <tbody>
              {(top?.items ?? []).map((a) => (
                <Tr key={a.id}>
                  <Td>
                    <Link href={`/accounts/${a.id}`} className="font-medium hover:underline">
                      {a.name}
                    </Link>
                    <div className="text-xs text-muted">{a.industry ?? "Unknown industry"}</div>
                  </Td>
                  <Td>
                    <GradeBadge grade={a.score_grade} score={a.icp_score} />
                  </Td>
                  <Td align="right">{a.intent_score ?? "—"}</Td>
                  <Td className="max-w-64">
                    <div className="truncate text-xs">{a.last_signal?.title ?? "—"}</div>
                    <div className="text-[11px] text-muted">{relTime(a.last_signal_at)}</div>
                  </Td>
                  <Td className="text-xs">{a.owner ?? <span className="text-warning">Unowned</span>}</Td>
                </Tr>
              ))}
            </tbody>
          </Table>
        </Panel>

        <Panel title="Guided demo" description="The fastest path through GTMOS">
          <ol className="space-y-2">
            {DEMO_PATH.map((step, i) => (
              <li key={step.label}>
                <Link
                  href={step.href(ws)}
                  className="group flex items-center gap-3 rounded-md border border-border px-3 py-2 text-xs hover:bg-panel-2"
                >
                  <span className="grid size-5 shrink-0 place-items-center rounded-full bg-panel-2 text-[11px] font-medium text-muted">
                    {i + 1}
                  </span>
                  <span className="flex-1 text-text">{step.label}</span>
                  <ArrowRight className="size-3.5 text-subtle group-hover:text-text" aria-hidden />
                </Link>
              </li>
            ))}
          </ol>
        </Panel>
      </div>

      <div className="grid gap-4 lg:grid-cols-3">
        <Panel
          title="System health"
          description="From the GTM Stack Inspector"
          actions={
            <Link href="/stack-inspector" className="text-xs text-accent-text hover:underline">
              Inspect
            </Link>
          }
        >
          {inspector ? (
            <ul className="space-y-2">
              {inspector.sections.map((s) => (
                <li key={s.key} className="flex items-start gap-2 text-xs">
                  <StatusDot status={s.status} />
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center justify-between gap-2">
                      <span className="font-medium text-text">{s.title}</span>
                      <StatusBadge status={s.status} />
                    </div>
                    <p className="mt-0.5 text-muted">{s.headline}</p>
                  </div>
                </li>
              ))}
            </ul>
          ) : (
            <p className="text-xs text-muted">Unavailable.</p>
          )}
        </Panel>

        <Panel
          title="Fresh buying signals"
          description="High-confidence signals · 14 days"
          actions={
            <Link href="/signals" className="text-xs text-accent-text hover:underline">
              Signal feed
            </Link>
          }
        >
          <ul className="space-y-3">
            {(signals?.items ?? []).map((s) => (
              <li key={s.id} className="text-xs">
                <div className="flex items-center justify-between gap-2">
                  <Link href={`/accounts/${s.account_id}`} className="truncate font-medium hover:underline">
                    {s.account_name}
                  </Link>
                  <span className="shrink-0 text-muted">{relTime(s.observed_at)}</span>
                </div>
                <div className="mt-0.5 text-muted">
                  {titleCase(s.signal_type)} · {s.title}
                </div>
              </li>
            ))}
          </ul>
        </Panel>

        <Panel title="Does the score predict outcomes?" description="Meeting rate by grade · contacted accounts, 180 days">
          {grades?.rows.length ? (
            <>
              <HBarList
                items={grades.rows
                  .filter((r) => r.key !== "unknown")
                  .map((r) => ({
                    key: r.key,
                    label: `Grade ${r.key}`,
                    value: r.meeting_rate,
                    display: pct(r.meeting_rate),
                    sub: `${num(r.meetings)} meetings / ${num(r.contacted)} contacted${r.low_sample ? " · small sample" : ""}`,
                    muted: r.low_sample,
                  }))}
              />
              <p className="mt-3 text-[11px] text-muted">{grades.note}</p>
            </>
          ) : (
            <p className="text-xs text-muted">Not enough data.</p>
          )}
        </Panel>
      </div>

      <Panel title="Outbound" description={`Last ${o.window_days} days · no GTMOS decision uses open rates`}>
        <div className="grid grid-cols-2 gap-4 sm:grid-cols-4 lg:grid-cols-7">
          {[
            ["Drafts awaiting review", num(o.messages_in_review)],
            ["Emails sent", num(o.emails_sent)],
            ["Delivered", num(o.emails_delivered)],
            ["Replies", num(o.replies)],
            ["Reply rate", pct(o.reply_rate)],
            ["Positive replies", num(o.positive_replies)],
            ["Opened (unreliable)", num(o.emails_opened)],
          ].map(([label, value]) => (
            <div key={label}>
              <div className="text-xs text-muted">{label}</div>
              <div className="tabular mt-1 text-base font-semibold">{value}</div>
            </div>
          ))}
        </div>
        <p className="mt-3 text-[11px] text-muted">{o.open_rate_caveat}</p>
      </Panel>
    </div>
  );
}
