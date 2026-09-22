import { ChevronRight } from "lucide-react";
import Link from "next/link";

import { describeCondition } from "@/components/systems/conditions";
import { FilterTabs } from "@/components/systems/filter-tabs";
import { Mono } from "@/components/systems/mono";
import { Badge, DemoBadge, StatusBadge } from "@/components/ui/badge";
import { PageHeader } from "@/components/ui/page-header";
import { Panel } from "@/components/ui/panel";
import { ScoreBar } from "@/components/ui/score-bar";
import { StatCell, StatGrid } from "@/components/ui/stat";
import { EmptyState, ErrorState } from "@/components/ui/states";
import { Table, Td, Th, THead, Tr } from "@/components/ui/table";
import { api, settle } from "@/lib/api";
import { num, pct, relTime, segment, titleCase } from "@/lib/format";
import { cn } from "@/lib/utils";

import { destinationLabel } from "./destination";
import { RoutingSimulator } from "./simulator";
import type { DecisionItem, DecisionList, RoutingRuleItem, TeamUser } from "./types";

export const metadata = { title: "Routing" };

const VIEWS = [
  { key: "all", label: "All decisions", query: "" },
  { key: "conflicts", label: "Conflicts only", query: "&conflicts_only=true" },
  { key: "unmatched", label: "Unmatched", query: "&outcome=unmatched" },
  { key: "kept_owner", label: "Kept owner", query: "&outcome=kept_owner" },
] as const;

export default async function RoutingPage(props: PageProps<"/routing">) {
  const sp = await props.searchParams;
  const raw = Array.isArray(sp.view) ? sp.view[0] : sp.view;
  const view = VIEWS.find((v) => v.key === raw) ?? VIEWS[0];

  const [rules, decisions, users] = await settle(
    api<RoutingRuleItem[]>("/routing/rules"),
    api<DecisionList>(`/routing/decisions?limit=50${view.query}`),
    api<TeamUser[]>("/users"),
  );

  if (!rules) {
    return (
      <div className="space-y-6">
        <PageHeader title="Routing" />
        <ErrorState title="Couldn't load routing rules" message="The GTMOS API did not respond. Start the backend and reload." />
      </div>
    );
  }

  const counts = decisions?.counts ?? {};
  const totalDecisions = (counts.assigned ?? 0) + (counts.kept_owner ?? 0) + (counts.unmatched ?? 0);
  const activeRules = rules.filter((r) => r.is_active).length;
  const overloaded = (users ?? []).filter((u) => u.is_active && u.capacity > 0 && (u.utilization ?? 0) > 1).length;
  const userNames = Object.fromEntries((users ?? []).map((u) => [u.user_id, u.name]));
  const ruleNames = Object.fromEntries(rules.map((r) => [r.key, r.name]));

  return (
    <div className="space-y-6">
      <PageHeader
        title="Routing"
        eyebrow={
          <span className="inline-flex items-center gap-2">
            Systems · routing engine <DemoBadge />
          </span>
        }
        description="Deterministic account routing. Rules are data, evaluated in a fixed order, and every decision records which rules matched, which lost and why, so an owner assignment can always be explained."
      />

      <StatGrid>
        <StatCell label="Active rules" value={`${activeRules} / ${rules.length}`} />
        <StatCell label="Decisions" value={num(totalDecisions)} sub="all time" />
        <StatCell label="Assigned" value={num(counts.assigned ?? 0)} />
        <StatCell label="Kept existing owner" value={num(counts.kept_owner ?? 0)} />
        <StatCell
          label="Unmatched"
          value={num(counts.unmatched ?? 0)}
          sub={totalDecisions ? `${pct((counts.unmatched ?? 0) / totalDecisions)} to RevOps triage` : undefined}
        />
        <StatCell label="Reps over capacity" value={num(overloaded)} sub={users ? `of ${users.filter((u) => u.is_active).length} active` : undefined} />
      </StatGrid>

      <Panel
        title="Routing simulator"
        description="Describe an account and see exactly how the live rules would route it: winner, owner, explanation and conflicts"
      >
        <RoutingSimulator
          ruleNames={ruleNames}
          users={(users ?? []).map((u) => ({ id: u.user_id, name: u.name, team: u.team, is_active: u.is_active }))}
        />
      </Panel>

      <Panel title="Rules" description="Evaluated in priority order · decision counts over 90 days" bodyClassName="p-0">
        <div className="border-b border-border bg-panel-2/50 px-4 py-2 text-[11px] text-muted">
          <span className="font-medium text-text">Conflict resolution:</span> when several rules match, the lowest priority number wins; on a tie
          the more specific rule (more conditions) wins; then the rule key alphabetically. Existing active owners are kept unless the
          winning rule overrides ownership.
        </div>
        <Table>
          <caption className="sr-only">Routing rules ordered by priority</caption>
          <THead>
            <tr>
              <Th align="right">Priority</Th>
              <Th>Rule</Th>
              <Th>When</Th>
              <Th>Assign to</Th>
              <Th>Owner</Th>
              <Th align="right">Decisions · 90d</Th>
            </tr>
          </THead>
          <tbody>
            {rules.map((r) => (
              <Tr key={r.id} className={cn(!r.is_active && "opacity-60")}>
                <Td align="right" className="align-top font-medium">
                  {r.priority}
                </Td>
                <Td className="min-w-56 max-w-80 align-top">
                  <div className="flex flex-wrap items-center gap-1.5">
                    <span className="text-xs font-medium">{r.name}</span>
                    {!r.is_active && <Badge>Inactive</Badge>}
                  </div>
                  {r.description && <p className="mt-0.5 text-[11px] text-muted">{r.description}</p>}
                  <Mono>{r.key}</Mono>
                </Td>
                <Td className="min-w-52 align-top">
                  <ul className="space-y-0.5 text-xs">
                    {r.conditions.map((c, i) => (
                      <li key={i}>
                        {i > 0 && <span className="mr-1 text-[10px] font-medium uppercase text-subtle">and</span>}
                        {describeCondition(c)}
                      </li>
                    ))}
                  </ul>
                </Td>
                <Td className="align-top text-xs">
                  {r.assign_strategy === "user" ? (
                    <>
                      <div className="font-medium">{r.assign_user ?? "Named user"}</div>
                      <div className="text-[11px] text-muted">Direct · falls back to {r.assign_team ?? "team"} pool</div>
                    </>
                  ) : (
                    <>
                      <div className="font-medium">{r.assign_team} pool</div>
                      <div className="text-[11px] text-muted">Least-loaded active member</div>
                    </>
                  )}
                </Td>
                <Td className="align-top">
                  {r.overrides_existing_owner ? <Badge tone="warning">Overrides</Badge> : <Badge>Respects</Badge>}
                </Td>
                <Td align="right" className="align-top">
                  {num(r.decisions_90d)}
                </Td>
              </Tr>
            ))}
          </tbody>
        </Table>
      </Panel>

      <div className="grid gap-4 xl:grid-cols-5">
        <Panel
          title="Team capacity"
          description="Open accounts vs capacity · pools assign to the least-loaded active member"
          className="xl:col-span-2"
          bodyClassName="p-0"
        >
          {users?.length ? <CapacityTable users={users} /> : <EmptyState title="No users" description="Seed users to enable pool routing." />}
        </Panel>

        <Panel
          title="Recent decisions"
          description="Latest 50 · expand a row to read the recorded explanation"
          className="xl:col-span-3"
          bodyClassName="p-0"
        >
          <FilterTabs
            label="Filter decisions"
            active={view.key}
            className="px-2"
            tabs={VIEWS.map((v) => ({
              key: v.key,
              label: v.label,
              href: v.key === "all" ? "/routing#decisions" : `/routing?view=${v.key}#decisions`,
              count: v.key === "all" ? totalDecisions : v.key === "conflicts" ? null : (counts[v.key] ?? 0),
            }))}
          />
          <div id="decisions">
            {!decisions ? (
              <div className="p-4">
                <ErrorState title="Couldn't load decisions" />
              </div>
            ) : decisions.items.length ? (
              <DecisionsTable items={decisions.items} userNames={userNames} />
            ) : (
              <EmptyState title="No decisions in this view" />
            )}
          </div>
        </Panel>
      </div>
    </div>
  );
}

function CapacityTable({ users }: { users: TeamUser[] }) {
  const sorted = [...users].sort((a, b) => (a.team ?? "").localeCompare(b.team ?? "") || a.name.localeCompare(b.name));
  return (
    <Table>
      <caption className="sr-only">Team capacity and utilization</caption>
      <THead>
        <tr>
          <Th>Rep</Th>
          <Th align="right">Open / cap</Th>
          <Th className="w-40">Utilization</Th>
        </tr>
      </THead>
      <tbody>
        {sorted.map((u) => {
          const util = u.utilization ?? 0;
          const tone = !u.is_active ? "muted" : util > 1 ? "danger" : util > 0.85 ? "warning" : "success";
          return (
            <Tr key={u.user_id}>
              <Td>
                <div className="flex flex-wrap items-center gap-1.5">
                  <span className={cn("text-xs font-medium", !u.is_active && "text-muted")}>{u.name}</span>
                  {!u.is_active && (
                    <Badge tone="danger" title="Inactive users are skipped by pool routing; their accounts are reassigned on the next decision">
                      Inactive
                    </Badge>
                  )}
                </div>
                <div className="text-[11px] text-muted">{u.team ?? "No team"}</div>
              </Td>
              <Td align="right" className="whitespace-nowrap text-xs">
                {num(u.open_accounts)} / {u.capacity ? num(u.capacity) : "—"}
              </Td>
              <Td>
                {u.capacity > 0 ? (
                  <div className="flex items-center gap-2">
                    <ScoreBar value={Math.min(util, 1)} max={1} tone={tone} className="flex-1" />
                    <span className={cn("tabular w-11 text-right text-[11px]", util > 1 && u.is_active ? "font-medium text-danger" : "text-muted")}>
                      {pct(util, 0)}
                    </span>
                  </div>
                ) : (
                  <span className="text-[11px] text-muted">Not routable (no capacity)</span>
                )}
              </Td>
            </Tr>
          );
        })}
      </tbody>
    </Table>
  );
}

function DecisionsTable({ items, userNames }: { items: DecisionItem[]; userNames: Record<string, string> }) {
  return (
    <Table>
      <caption className="sr-only">Recent routing decisions</caption>
      <THead>
        <tr>
          <Th>Account</Th>
          <Th>Outcome</Th>
          <Th>Rule</Th>
          <Th>Why</Th>
          <Th>Decided</Th>
        </tr>
      </THead>
      <tbody>
        {items.map((d) => (
          <Tr key={d.id}>
            <Td className="align-top">
              <Link href={`/accounts/${d.account_id}`} className="text-xs font-medium hover:underline">
                {d.account_name}
              </Link>
              <div className="text-[11px] text-muted">
                {segment(d.segment)} · {d.region ?? "No region"}
              </div>
            </Td>
            <Td className="align-top">
              <StatusBadge status={d.outcome} label={d.outcome === "kept_owner" ? "kept owner" : undefined} />
              <div className="mt-0.5 text-[11px] text-text">{d.assigned_to ?? <span className="text-muted">RevOps triage</span>}</div>
            </Td>
            <Td className="max-w-48 align-top text-[11px]">
              <div className="truncate" title={d.rule_name ?? undefined}>
                {d.rule_name ?? <span className="text-muted">No rule matched</span>}
              </div>
              {d.conflicts.length > 0 && (
                <Badge tone="warning" className="mt-0.5">
                  {d.conflicts.length} conflict{d.conflicts.length > 1 ? "s" : ""}
                </Badge>
              )}
            </Td>
            <Td className="min-w-64 max-w-md align-top">
              <details className="group">
                <summary className="flex cursor-pointer list-none items-start gap-1 text-[11px] text-muted hover:text-text [&::-webkit-details-marker]:hidden">
                  <ChevronRight className="mt-0.5 size-3 shrink-0 transition-transform group-open:rotate-90" aria-hidden />
                  <span className="line-clamp-1 group-open:hidden">{d.explanation[0] ?? "No explanation recorded"}</span>
                  <span className="hidden group-open:inline">Explanation</span>
                </summary>
                <ol className="mt-1 list-decimal space-y-1 pl-6 text-[11px] text-text">
                  {d.explanation.map((line, i) => (
                    <li key={i}>{line}</li>
                  ))}
                </ol>
                {d.conflicts.length > 0 && (
                  <ul className="mt-1.5 space-y-0.5 pl-4 text-[11px] text-muted">
                    {d.conflicts.map((c) => (
                      <li key={c.rule}>
                        Lost: {c.name} → {destinationLabel(c.destination, userNames)} ({c.lost_because})
                      </li>
                    ))}
                  </ul>
                )}
              </details>
            </Td>
            <Td className="whitespace-nowrap align-top text-[11px] text-muted" title={d.decided_at}>
              {relTime(d.decided_at)}
              <div className="text-subtle">{titleCase(d.trigger)}</div>
            </Td>
          </Tr>
        ))}
      </tbody>
    </Table>
  );
}
