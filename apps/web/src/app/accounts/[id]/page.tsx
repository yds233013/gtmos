import Link from "next/link";
import { notFound } from "next/navigation";

import { AccountActions } from "@/components/account/account-actions";
import { AutomationPanel } from "@/components/account/automation-panel";
import { CommitteePanel } from "@/components/account/committee-panel";
import { FactsPanel } from "@/components/account/facts-panel";
import { OutreachPanel } from "@/components/account/outreach-panel";
import { ResearchPanel } from "@/components/account/research-panel";
import { ScorePanel } from "@/components/account/score-panel";
import { Timeline } from "@/components/account/timeline";
import { Badge, DemoBadge, GradeBadge, StatusBadge } from "@/components/ui/badge";
import { Panel } from "@/components/ui/panel";
import { ErrorState } from "@/components/ui/states";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { api, ApiError } from "@/lib/api";
import { money, num, pct, relTime, segment, titleCase } from "@/lib/format";
import type { AccountDetail } from "@/lib/types";

export async function generateMetadata(props: PageProps<"/accounts/[id]">) {
  const { id } = await props.params;
  try {
    const d = await api<AccountDetail>(`/accounts/${id}`);
    return { title: d.account.name };
  } catch {
    return { title: "Account" };
  }
}

function SignalList({ data, limit }: { data: AccountDetail; limit?: number }) {
  const items = limit ? data.signals.slice(0, limit) : data.signals;
  if (!items.length) return <p className="text-xs text-muted">No signals recorded.</p>;
  return (
    <ul className="divide-y divide-border">
      {items.map((s) => (
        <li key={s.id} className="py-2.5 text-xs first:pt-0">
          <div className="flex flex-wrap items-center gap-2">
            <Badge tone="info">{titleCase(s.signal_type)}</Badge>
            <span className="font-medium">{s.title}</span>
            <span className="ml-auto text-muted">{relTime(s.observed_at)}</span>
          </div>
          <p className="mt-1 text-muted">{s.explanation}</p>
          <div className="mt-0.5 text-[11px] text-subtle">
            {s.source} · confidence {pct(s.confidence, 0)} · strength {s.strength.toFixed(2)}
            {s.data_origin === "demo" ? " · demo" : " · live"}
          </div>
        </li>
      ))}
    </ul>
  );
}

export default async function AccountPage(props: PageProps<"/accounts/[id]">) {
  const { id } = await props.params;
  let data: AccountDetail;
  try {
    data = await api<AccountDetail>(`/accounts/${id}`);
  } catch (e) {
    if (e instanceof ApiError && (e.status === 404 || e.status === 422)) notFound();
    return <ErrorState message={e instanceof Error ? e.message : "Failed to load account"} />;
  }
  const a = data.account;
  const openOpps = data.opportunities.filter((o) => !o.stage.startsWith("closed"));
  const reviewDrafts = data.drafts.filter((d) => d.status === "review").length;

  return (
    <div className="space-y-5">
      <div className="text-xs text-muted">
        <Link href="/accounts" className="hover:text-text">
          Accounts
        </Link>{" "}
        / {a.name}
      </div>

      <header className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <h1 className="text-xl font-semibold tracking-tight">{a.name}</h1>
            <GradeBadge grade={a.score_grade} score={a.icp_score} />
            {a.is_flagship && <Badge tone="accent">Flagship demo account</Badge>}
            {a.data_origin === "demo" && <DemoBadge />}
            {a.is_customer && <Badge tone="success">Customer</Badge>}
          </div>
          <div className="mt-1 text-sm text-muted">
            {a.domain ?? "No domain"} · {a.industry ?? "Unknown industry"} · {segment(a.segment)} ·{" "}
            {a.employee_count ? `${num(a.employee_count)} employees` : "size unknown"} · {a.city ?? a.region ?? "—"}
          </div>
          {a.description && <p className="mt-2 max-w-3xl text-sm text-muted">{a.description}</p>}
        </div>
        <dl className="grid shrink-0 grid-cols-3 gap-x-6 gap-y-1 text-xs lg:text-right">
          <dt className="text-muted">Owner</dt>
          <dt className="text-muted">Stage</dt>
          <dt className="text-muted">Intent</dt>
          <dd className="font-medium">{a.owner ?? <span className="text-warning">Unowned</span>}</dd>
          <dd className="font-medium">{titleCase(a.funnel_stage)}</dd>
          <dd className="tabular font-medium">{a.intent_score ?? "—"}/100</dd>
        </dl>
      </header>

      <div className="grid gap-4 lg:grid-cols-[1fr_380px]">
        <Panel title="Actions" description="Everything runs through the same audited services the workflows use">
          <AccountActions accountId={a.id} />
        </Panel>
        <Panel title="Recommended next action">
          <div className="flex items-start gap-2">
            <StatusBadge status={data.next_action.priority <= 2 ? "review" : "pending"} label={`P${data.next_action.priority}`} />
            <div>
              <div className="text-sm font-medium">{data.next_action.label}</div>
              <p className="mt-0.5 text-xs text-muted">{data.next_action.reason}</p>
            </div>
          </div>
          {reviewDrafts > 0 && (
            <Link href="/approvals" className="mt-3 inline-block text-xs text-accent-text hover:underline">
              {reviewDrafts} draft(s) awaiting approval →
            </Link>
          )}
        </Panel>
      </div>

      <Tabs defaultValue="overview">
        <TabsList aria-label="Account sections">
          <TabsTrigger value="overview">Overview</TabsTrigger>
          <TabsTrigger value="signals">Signals ({data.signals.length})</TabsTrigger>
          <TabsTrigger value="committee">Buying committee</TabsTrigger>
          <TabsTrigger value="research">Research</TabsTrigger>
          <TabsTrigger value="outreach">Outreach ({data.drafts.length})</TabsTrigger>
          <TabsTrigger value="activity">Activity</TabsTrigger>
          <TabsTrigger value="automation">Automation & audit</TabsTrigger>
        </TabsList>

        <TabsContent value="overview" className="space-y-4">
          {data.score ? <ScorePanel score={data.score} /> : <ErrorState title="Not scored yet" />}
          <div className="grid gap-4 xl:grid-cols-2">
            <FactsPanel data={data} />
            <div className="space-y-4">
              <Panel title="Recent signals" description="Why now">
                <SignalList data={data} limit={5} />
              </Panel>
              <Panel title="Opportunities" bodyClassName="p-0">
                {data.opportunities.length === 0 ? (
                  <p className="px-4 py-3 text-xs text-muted">No opportunities.</p>
                ) : (
                  <ul className="divide-y divide-border">
                    {data.opportunities.map((o) => (
                      <li key={o.id} className="flex flex-wrap items-center gap-2 px-4 py-2 text-xs">
                        <StatusBadge status={o.stage} />
                        <span className="font-medium">{o.name}</span>
                        <span className="tabular ml-auto font-medium">{money(o.amount_usd)}</span>
                        <span className="w-full text-muted">
                          Opened {relTime(o.opened_at)} · {o.owner ?? "no owner"} · source {o.campaign ?? o.lead_source ?? "—"}
                        </span>
                      </li>
                    ))}
                  </ul>
                )}
              </Panel>
            </div>
          </div>
          {openOpps.length === 0 && data.committee.length === 0 && (
            <p className="text-xs text-muted">No committee inferred yet: add contacts or run the workflow.</p>
          )}
        </TabsContent>

        <TabsContent value="signals">
          <Panel title="All signals" description="Signals decay by half-life and feed intent, timing and engagement points">
            <SignalList data={data} />
          </Panel>
        </TabsContent>

        <TabsContent value="committee">
          <CommitteePanel data={data} />
        </TabsContent>

        <TabsContent value="research">
          <ResearchPanel accountId={a.id} report={data.research} />
        </TabsContent>

        <TabsContent value="outreach">
          <OutreachPanel data={data} />
        </TabsContent>

        <TabsContent value="activity">
          <Timeline data={data} />
        </TabsContent>

        <TabsContent value="automation">
          <AutomationPanel data={data} />
        </TabsContent>
      </Tabs>
    </div>
  );
}
