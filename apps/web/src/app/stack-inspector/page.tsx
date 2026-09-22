import { ArrowRight, ArrowUpRight, CircleAlert, CircleCheck, TriangleAlert } from "lucide-react";
import Link from "next/link";

import { HBarList } from "@/components/charts/hbar-list";
import { EvidenceList, RawJson } from "@/components/insights/evidence";
import { RefreshButton } from "@/components/insights/refresh-button";
import { Badge, SimulatedBadge, StatusBadge, StatusDot } from "@/components/ui/badge";
import { PageHeader } from "@/components/ui/page-header";
import { Panel } from "@/components/ui/panel";
import { ErrorState } from "@/components/ui/states";
import { api, ApiError } from "@/lib/api";
import { dateTime, num, titleCase } from "@/lib/format";
import type { HealthStatus, Inspector, InspectorSection, Recommendation } from "@/lib/types";
import { cn } from "@/lib/utils";

export const metadata = { title: "GTM Stack Inspector" };

/** Where to go to fix or dig into each system. */
const SECTION_LINK: Record<string, { href: string; label: string }> = {
  crm: { href: "/settings", label: "CRM sync settings" },
  enrichment: { href: "/data-quality", label: "Data quality" },
  routing: { href: "/routing", label: "Routing rules" },
  data_quality: { href: "/data-quality", label: "Open issues" },
  product_signals: { href: "/signals", label: "Signal feed" },
  attribution: { href: "/pipeline", label: "Pipeline" },
  workflows: { href: "/workflows", label: "Workflow runs" },
  outbound: { href: "/campaigns", label: "Campaigns" },
};

const REC_LINK: Record<string, { href: string; label: string }> = {
  pql_routing: { href: "/workflows", label: "Open workflows" },
  enrichment_waterfall: { href: "/workflows", label: "Open workflows" },
  buying_signal_workflow: { href: "/workflows", label: "Open workflows" },
  reassign_departed: { href: "/routing", label: "Open routing" },
  territory_gap: { href: "/routing", label: "Open routing" },
  crm_dedupe: { href: "/data-quality", label: "Open data quality" },
  lifecycle_cleanup: { href: "/data-quality", label: "Open data quality" },
};

const STAGE_ORDER = ["contacted", "engaged", "meeting", "qualified", "opportunity"];

const OVERALL: Record<HealthStatus, { label: string; blurb: string; icon: typeof CircleCheck; box: string; ink: string }> = {
  healthy: {
    label: "Healthy",
    blurb: "Every system is inside its thresholds.",
    icon: CircleCheck,
    box: "border-success/30 bg-success-soft",
    ink: "text-success",
  },
  warning: {
    label: "Needs attention",
    blurb: "No system is broken, but some are drifting past their thresholds.",
    icon: TriangleAlert,
    box: "border-warning/30 bg-warning-soft",
    ink: "text-warning",
  },
  critical: {
    label: "Critical",
    blurb: "At least one system is failing badly enough to leak pipeline today.",
    icon: CircleAlert,
    box: "border-danger/30 bg-danger-soft",
    ink: "text-danger",
  },
};

const SEVERITY: Record<HealthStatus, number> = { critical: 0, warning: 1, healthy: 2 };

function Scorecard({ sections }: { sections: InspectorSection[] }) {
  return (
    <ul className="grid grid-cols-1 gap-px overflow-hidden rounded-lg border border-border bg-border sm:grid-cols-2 lg:grid-cols-4">
      {sections.map((s) => (
        <li key={s.key} className="bg-panel">
          <a href={`#${s.key}`} className="group flex h-full flex-col gap-1.5 px-4 py-3 hover:bg-panel-2">
            <span className="flex items-center justify-between gap-2">
              <span className="flex items-center gap-2 text-xs font-medium text-text">
                <StatusDot status={s.status} />
                {s.title}
              </span>
              <StatusBadge status={s.status} />
            </span>
            <span className="line-clamp-2 text-xs text-muted">{s.headline}</span>
          </a>
        </li>
      ))}
    </ul>
  );
}

function RecommendationItem({ rec }: { rec: Recommendation }) {
  const link = REC_LINK[rec.key];
  return (
    <li className="grid grid-cols-[1.75rem_1fr] gap-3 px-4 py-4 sm:grid-cols-[1.75rem_1fr_9rem]">
      <span
        aria-label={`Rank ${rec.rank}`}
        className={cn(
          "tabular grid size-7 place-items-center rounded-full text-xs font-semibold",
          rec.rank <= 3 ? "bg-accent-soft text-accent-text" : "bg-panel-2 text-muted",
        )}
      >
        {rec.rank}
      </span>
      <div className="min-w-0 space-y-2">
        <h3 className="text-sm font-semibold text-text">{rec.title}</h3>
        <dl className="space-y-1.5 text-xs">
          <div className="grid gap-0.5 sm:grid-cols-[3rem_1fr] sm:gap-2">
            <dt className="font-medium text-muted">Why</dt>
            <dd className="text-text">{rec.why}</dd>
          </div>
          <div className="grid gap-0.5 sm:grid-cols-[3rem_1fr] sm:gap-2">
            <dt className="font-medium text-muted">How</dt>
            <dd className="text-text">{rec.how}</dd>
          </div>
        </dl>
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5">
          <details className="text-xs">
            <summary className="cursor-pointer select-none text-muted hover:text-text">Evidence</summary>
            <div className="mt-2 max-w-xl rounded-md border border-border bg-panel-2/50 p-3">
              <EvidenceList evidence={rec.evidence} nested />
            </div>
          </details>
          {link && (
            <Link href={link.href} className="inline-flex items-center gap-1 text-xs text-accent-text hover:underline">
              {link.label}
              <ArrowRight className="size-3" aria-hidden />
            </Link>
          )}
        </div>
      </div>
      <div className="col-start-2 flex gap-4 sm:col-start-3 sm:flex-col sm:items-end sm:gap-1 sm:text-right">
        <div>
          <div className="tabular text-base font-semibold text-text">{num(rec.impact_accounts)}</div>
          <div className="text-[11px] text-muted">accounts affected</div>
        </div>
        <div>
          <div className={cn("tabular text-sm font-semibold", rec.priority_accounts > 0 ? "text-text" : "text-subtle")}>
            {num(rec.priority_accounts)}
          </div>
          <div className="text-[11px] text-muted">priority accounts</div>
        </div>
      </div>
    </li>
  );
}

function SectionPanel({ section }: { section: InspectorSection }) {
  const link = SECTION_LINK[section.key];
  return (
    <Panel
      id={section.key}
      className="scroll-mt-6"
      title={
        <span className="flex flex-wrap items-center gap-2">
          <StatusDot status={section.status} />
          {section.title}
        </span>
      }
      actions={
        <>
          {section.simulated && <SimulatedBadge />}
          <StatusBadge status={section.status} />
        </>
      }
    >
      <p className={cn("text-sm font-medium", section.status === "critical" ? "text-danger" : "text-text")}>
        {section.headline}
      </p>
      <div className="mt-3 rounded-md border border-border bg-panel-2/40 p-3">
        <div className="mb-2 flex items-center justify-between gap-2">
          <span className="text-[11px] font-semibold uppercase tracking-wide text-muted">Evidence</span>
          <span className="text-[11px] text-subtle">values behind the headline</span>
        </div>
        <EvidenceList evidence={section.evidence} />
      </div>
      <div className="mt-3 flex items-center justify-between gap-3">
        <RawJson value={section.evidence} />
        {link && (
          <Link href={link.href} className="inline-flex shrink-0 items-center gap-1 text-xs text-accent-text hover:underline">
            {link.label}
            <ArrowUpRight className="size-3" aria-hidden />
          </Link>
        )}
      </div>
    </Panel>
  );
}

export default async function StackInspectorPage() {
  let data: Inspector | null = null;
  let error: string | null = null;
  try {
    data = await api<Inspector>("/stack-inspector");
  } catch (e) {
    error = e instanceof ApiError ? e.message : "The inspection failed to run.";
  }

  const header = (
    <PageHeader
      title="GTM Stack Inspector"
      eyebrow={data ? `Inspected ${dateTime(data.generated_at)} · computed live from the GTMOS database` : "Systems audit"}
      description="An automated audit of the go-to-market stack: CRM sync, enrichment, routing, data quality, product signals, attribution, automation and outbound. Each finding shows the evidence behind it and ends in a ranked list of automations worth building."
      actions={<RefreshButton pendingLabel="Inspecting…">Re-run inspection</RefreshButton>}
    />
  );

  if (!data) {
    return (
      <div>
        {header}
        <ErrorState title="Couldn't run the inspection" message={error ?? undefined} />
      </div>
    );
  }

  const overall = OVERALL[data.overall_status] ?? OVERALL.warning;
  const OverallIcon = overall.icon;
  const worst = [...data.sections].sort((a, b) => SEVERITY[a.status] - SEVERITY[b.status]).filter((s) => s.status !== "healthy");
  const stageRank = (s: string) => (STAGE_ORDER.includes(s) ? STAGE_ORDER.indexOf(s) : STAGE_ORDER.length);
  const stuck = Object.entries(data.context.stuck_by_stage).sort((a, b) => stageRank(a[0]) - stageRank(b[0]));
  const totalImpact = data.recommendations.reduce((acc, r) => acc + r.priority_accounts, 0);

  return (
    <div className="space-y-6">
      {header}

      <section aria-labelledby="overall-status" className="grid gap-4 lg:grid-cols-3">
        <div className={cn("rounded-lg border p-4 lg:col-span-2", overall.box)}>
          <div className="flex items-start gap-3">
            <OverallIcon className={cn("mt-0.5 size-5 shrink-0", overall.ink)} aria-hidden />
            <div className="min-w-0 flex-1">
              <h2 id="overall-status" className={cn("text-base font-semibold", overall.ink)}>
                Overall: {overall.label}
              </h2>
              <p className="mt-0.5 text-xs text-muted">{overall.blurb}</p>
              <div className="mt-3 flex flex-wrap gap-2">
                <Badge tone="danger">{num(data.summary.critical)} critical</Badge>
                <Badge tone="warning">{num(data.summary.warning)} warning</Badge>
                <Badge tone="success">{num(data.summary.healthy)} healthy</Badge>
              </div>
              {worst.length > 0 && (
                <ul className="mt-3 space-y-1 text-xs">
                  {worst.slice(0, 3).map((s) => (
                    <li key={s.key} className="flex items-start gap-2">
                      <StatusDot status={s.status} />
                      <span className="min-w-0">
                        <a href={`#${s.key}`} className="font-medium text-text hover:underline">
                          {s.title}
                        </a>
                        <span className="text-muted"> · {s.headline}</span>
                      </span>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          </div>
        </div>
        <Panel title="Why it matters" description="Accounts stalled in the funnel right now">
          <div className="mb-3 flex items-baseline gap-4">
            <div>
              <div className="tabular text-xl font-semibold text-text">{num(data.context.stuck_accounts)}</div>
              <div className="text-[11px] text-muted">stuck accounts</div>
            </div>
            <div>
              <div className="tabular text-xl font-semibold text-text">{num(data.context.open_opportunities)}</div>
              <div className="text-[11px] text-muted">open opportunities</div>
            </div>
          </div>
          <HBarList
            items={stuck.map(([stage, count]) => ({
              key: stage,
              label: titleCase(stage),
              value: count,
              display: num(count),
            }))}
          />
        </Panel>
      </section>

      <section aria-labelledby="scorecard-heading" className="space-y-2">
        <h2 id="scorecard-heading" className="text-sm font-semibold text-text">
          System scorecard
        </h2>
        <Scorecard sections={data.sections} />
      </section>

      <Panel
        title="Automation opportunities"
        description={`Ranked by revenue impact · ${num(totalImpact)} priority accounts across ${data.recommendations.length} fixes`}
        bodyClassName="p-0"
      >
        {data.recommendations.length ? (
          <ol className="divide-y divide-border">
            {[...data.recommendations]
              .sort((a, b) => a.rank - b.rank)
              .map((r) => (
                <RecommendationItem key={r.key} rec={r} />
              ))}
          </ol>
        ) : (
          <p className="px-4 py-6 text-center text-xs text-muted">No automation gaps detected. Nothing to recommend.</p>
        )}
      </Panel>

      <section aria-labelledby="findings-heading" className="space-y-3">
        <div className="flex flex-wrap items-baseline justify-between gap-2">
          <h2 id="findings-heading" className="text-sm font-semibold text-text">
            Findings by system
          </h2>
          <span className="text-[11px] text-muted">Sections marked SIMULATED read from a demo adapter, not a live vendor.</span>
        </div>
        <div className="grid gap-4 lg:grid-cols-2">
          {data.sections.map((s) => (
            <SectionPanel key={s.key} section={s} />
          ))}
        </div>
      </section>

      <div className="rounded-lg border border-border bg-panel px-4 py-3 text-xs text-muted">
        <span className="font-medium text-text">Method.</span> {data.method} No number on this page is estimated or generated by a
        model; re-running the inspection re-executes every query.{" "}
        <span className="font-mono text-[11px]">apps/api/src/gtmos/services/stack_inspector.py</span>
      </div>
    </div>
  );
}
