import Link from "next/link";

import { FilterTabs } from "@/components/systems/filter-tabs";
import { Mono } from "@/components/systems/mono";
import { ActionButton } from "@/components/ui/action-button";
import { Badge, DemoBadge, StatusBadge } from "@/components/ui/badge";
import { PageHeader } from "@/components/ui/page-header";
import { Panel } from "@/components/ui/panel";
import { StatCell, StatGrid } from "@/components/ui/stat";
import { EmptyState, ErrorState } from "@/components/ui/states";
import { Table, Td, Th, THead, Tr } from "@/components/ui/table";
import { api, settle } from "@/lib/api";
import { dateTime, num, relTime, titleCase } from "@/lib/format";
import { cn } from "@/lib/utils";

import type { DqIssue, DqRule, DqSummary, IssueStatus } from "./types";

export const metadata = { title: "Data Quality" };

const STATUSES: IssueStatus[] = ["open", "resolved", "ignored"];
const SEV_ORDER = { high: 0, medium: 1, low: 2 } as const;
const ISSUE_LIMIT = 200;

function first(v: string | string[] | undefined): string | undefined {
  return Array.isArray(v) ? v[0] : v;
}

function href(rule: string | undefined, status: IssueStatus): string {
  const p = new URLSearchParams();
  if (rule) p.set("rule", rule);
  if (status !== "open") p.set("status", status);
  const s = p.toString();
  return `/data-quality${s ? `?${s}` : ""}#issues`;
}

export default async function DataQualityPage(props: PageProps<"/data-quality">) {
  const sp = await props.searchParams;
  const status = (STATUSES.find((s) => s === first(sp.status)) ?? "open") as IssueStatus;
  const [summary] = await settle(api<DqSummary>("/data-quality"));
  const ruleKey = summary?.rules.some((r) => r.key === first(sp.rule)) ? first(sp.rule) : undefined;

  const q = new URLSearchParams({ status, limit: String(ISSUE_LIMIT) });
  if (ruleKey) q.set("rule", ruleKey);
  const [issues] = await settle(api<{ items: DqIssue[] }>(`/data-quality/issues?${q.toString()}`));

  if (!summary) {
    return (
      <div className="space-y-6">
        <PageHeader title="Data quality" />
        <ErrorState title="Couldn't load data quality" message="The GTMOS API did not respond. Start the backend and reload." />
      </div>
    );
  }

  const rules = [...summary.rules].sort((a, b) => SEV_ORDER[a.severity] - SEV_ORDER[b.severity] || b.open - a.open);
  const selected = rules.find((r) => r.key === ruleKey);
  const highOpen = rules.filter((r) => r.severity === "high").reduce((a, r) => a + r.open, 0);
  const ignoredTotal = rules.reduce((a, r) => a + r.ignored, 0);
  const rulesFiring = rules.filter((r) => r.open > 0).length;
  const statusCount = (s: IssueStatus) => (selected ? selected[s] : s === "open" ? summary.open_total : s === "resolved" ? summary.resolved_total : ignoredTotal);
  const ruleLabel = Object.fromEntries(rules.map((r) => [r.key, r.label]));
  const items = issues?.items ?? [];

  return (
    <div className="space-y-6">
      <PageHeader
        title="Data quality"
        eyebrow={
          <span className="inline-flex items-center gap-2">
            Systems · CRM hygiene <DemoBadge />
          </span>
        }
        description="Rules scan accounts and contacts for problems that silently break routing, scoring, outreach and reporting. Each issue carries a suggested fix; applying or ignoring one is written to the audit log with the actor, before and after values."
        actions={
          <ActionButton path="/data-quality/scan" variant="primary" size="md">
            Run scan
          </ActionButton>
        }
      />

      <StatGrid>
        <StatCell label="Open issues" value={num(summary.open_total)} sub={`${rulesFiring} of ${rules.length} rules firing`} />
        <StatCell label="High severity open" value={<span className={cn(highOpen > 0 && "text-danger")}>{num(highOpen)}</span>} />
        <StatCell label="Resolved" value={num(summary.resolved_total)} sub="via audited remediation" />
        <StatCell label="Ignored" value={num(ignoredTotal)} sub="audited" />
        <StatCell label="Rules" value={num(rules.length)} />
        <StatCell label="Last scan" value={<span className="text-base">{relTime(summary.last_scan_at)}</span>} sub={dateTime(summary.last_scan_at)} />
      </StatGrid>

      <section aria-labelledby="dq-rules">
        <div className="mb-3 flex items-baseline justify-between gap-3">
          <h2 id="dq-rules" className="text-sm font-semibold text-text">
            Rules
          </h2>
          {selected && (
            <Link href={href(undefined, status)} className="text-xs text-accent-text hover:underline">
              Clear rule filter
            </Link>
          )}
        </div>
        <ul className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
          {rules.map((r) => (
            <RuleCard key={r.key} rule={r} active={r.key === ruleKey} status={status} />
          ))}
        </ul>
      </section>

      <Panel
        id="issues"
        title={selected ? selected.label : "All issues"}
        description={
          selected
            ? selected.why
            : `Highest severity first${items.length >= ISSUE_LIMIT ? ` · showing the first ${ISSUE_LIMIT}` : ""} · pick a rule above to focus`
        }
        bodyClassName="p-0"
      >
        <FilterTabs
          label="Filter issues by status"
          active={status}
          className="px-2"
          tabs={STATUSES.map((s) => ({ key: s, label: titleCase(s), href: href(ruleKey, s), count: statusCount(s) }))}
        />
        {!issues ? (
          <div className="p-4">
            <ErrorState title="Couldn't load issues" />
          </div>
        ) : items.length ? (
          <Table>
            <caption className="sr-only">Data quality issues</caption>
            <THead>
              <tr>
                <Th>Severity</Th>
                <Th>Issue</Th>
                <Th>Record</Th>
                <Th>Suggested remediation</Th>
                <Th align="right">{status === "open" ? "Actions" : "Closed"}</Th>
              </tr>
            </THead>
            <tbody>
              {items.map((i) => (
                <IssueRow key={i.id} issue={i} ruleLabel={selected ? undefined : ruleLabel[i.rule_key]} />
              ))}
            </tbody>
          </Table>
        ) : (
          <EmptyState
            title={status === "open" ? "No open issues" : `No ${status} issues`}
            description={status === "open" ? "Run a scan to re-check the data." : "Nothing has been closed this way yet."}
          />
        )}
        <p className="border-t border-border px-4 py-2 text-[11px] text-muted">
          Every fix and ignore is recorded as an audit event (who, when, before → after). Merges re-parent related records rather than
          deleting history. Issues that need a human, such as a missing website, have no automatic fix.
        </p>
      </Panel>
    </div>
  );
}

const SEV_TONE = { high: "danger", medium: "warning", low: "neutral" } as const;

function RuleCard({ rule: r, active, status }: { rule: DqRule; active: boolean; status: IssueStatus }) {
  return (
    <li>
      <Link
        href={href(active ? undefined : r.key, status)}
        aria-current={active ? "true" : undefined}
        className={cn(
          "flex h-full flex-col rounded-lg border bg-panel p-3 transition-colors hover:bg-panel-2/60",
          active ? "border-accent ring-1 ring-accent" : "border-border",
        )}
      >
        <div className="flex items-start justify-between gap-2">
          <span className="text-xs font-medium text-text">{r.label}</span>
          <Badge tone={SEV_TONE[r.severity]}>{r.severity}</Badge>
        </div>
        <p className="mt-1 flex-1 text-[11px] leading-4 text-muted">{r.why}</p>
        <div className="mt-2 flex items-baseline gap-3 text-[11px] text-muted">
          <span>
            <span className={cn("tabular text-base font-semibold", r.open ? "text-text" : "text-subtle")}>{num(r.open)}</span> open
          </span>
          {r.resolved > 0 && <span className="tabular">{num(r.resolved)} resolved</span>}
          {r.ignored > 0 && <span className="tabular">{num(r.ignored)} ignored</span>}
        </div>
      </Link>
    </li>
  );
}

interface RecordRef {
  id: string;
  name?: string;
  email?: string;
  title?: string;
  domain?: string;
}

function detailRecords(d: Record<string, unknown> | null): RecordRef[] {
  const recs = d?.records;
  return Array.isArray(recs) ? (recs.filter((r) => r && typeof r === "object" && "id" in r) as RecordRef[]) : [];
}

function str(d: Record<string, unknown> | null, key: string): string | undefined {
  const v = d?.[key];
  return typeof v === "string" ? v : undefined;
}

function EntityCell({ issue: i }: { issue: DqIssue }) {
  const recs = detailRecords(i.details);
  if (i.entity_type === "account") {
    if (recs.length) {
      return (
        <ul className="space-y-0.5">
          {recs.map((r, n) => (
            <li key={r.id} className="text-[11px]">
              <Link href={`/accounts/${r.id}`} className="font-medium text-text hover:underline">
                {r.name ?? "Account"}
              </Link>
              {n === 0 && <span className="ml-1 text-subtle">(primary)</span>}
              {r.domain && <div className="font-mono text-muted">{r.domain}</div>}
            </li>
          ))}
        </ul>
      );
    }
    return (
      <Link href={`/accounts/${i.entity_id}`} className="text-[11px] font-medium hover:underline">
        {str(i.details, "name") ?? "Open account"}
      </Link>
    );
  }
  if (i.entity_type === "contact") {
    if (recs.length) {
      return (
        <ul className="space-y-1">
          {recs.map((r, n) => (
            <li key={r.id} className="text-[11px]">
              <span className="font-mono text-text">{r.email?.trim() || "no email"}</span>
              {n === 0 && <span className="ml-1 text-subtle">(primary)</span>}
              {r.title && <div className="text-muted">{r.title}</div>}
            </li>
          ))}
        </ul>
      );
    }
    return (
      <div className="text-[11px]">
        <div className="text-muted">Contact</div>
        {str(i.details, "email") && <div className="font-mono text-text">{str(i.details, "email")}</div>}
        {str(i.details, "title") && <div className="text-muted">{str(i.details, "title")}</div>}
      </div>
    );
  }
  return <span className="text-[11px] text-muted">{titleCase(i.entity_type)}</span>;
}

function IssueRow({ issue: i, ruleLabel }: { issue: DqIssue; ruleLabel?: string }) {
  const fix = i.suggested_fix;
  const manual = !fix || fix.action === "manual";
  return (
    <Tr>
      <Td className="align-top">
        <Badge tone={SEV_TONE[i.severity]}>{i.severity}</Badge>
      </Td>
      <Td className="min-w-56 max-w-80 align-top">
        <div className="text-xs font-medium text-text">{i.title}</div>
        <div className="mt-0.5 text-[11px] text-muted">
          {ruleLabel && <>{ruleLabel} · </>}detected {relTime(i.detected_at)}
        </div>
      </Td>
      <Td className="min-w-40 align-top">
        <EntityCell issue={i} />
      </Td>
      <Td className="min-w-56 max-w-96 align-top">
        {fix ? (
          <>
            <p className="text-[11px] text-text">{fix.description}</p>
            <div className="mt-0.5">
              {manual ? <Badge>manual fix</Badge> : <Mono>{fix.action}</Mono>}
            </div>
          </>
        ) : (
          <span className="text-[11px] text-muted">No suggestion</span>
        )}
      </Td>
      <Td align="right" className="align-top">
        {i.status === "open" ? (
          <div className="flex flex-wrap items-start justify-end gap-1.5">
            {!manual && (
              <ActionButton path={`/data-quality/issues/${i.id}/remediate`} confirmLabel="Confirm fix">
                Fix
              </ActionButton>
            )}
            <ActionButton path={`/data-quality/issues/${i.id}/ignore`} variant="ghost">
              Ignore
            </ActionButton>
          </div>
        ) : (
          <div className="text-[11px]">
            <StatusBadge status={i.status === "resolved" ? "succeeded" : "skipped"} label={i.status} />
            <div className="mt-0.5 text-muted">{relTime(i.resolved_at)}</div>
            {i.resolved_by && <div className="max-w-40 truncate text-subtle" title={i.resolved_by}>{i.resolved_by}</div>}
          </div>
        )}
      </Td>
    </Tr>
  );
}
