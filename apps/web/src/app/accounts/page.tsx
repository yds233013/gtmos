import Link from "next/link";

import { Badge, DemoBadge, GradeBadge } from "@/components/ui/badge";
import { PageHeader } from "@/components/ui/page-header";
import { Panel } from "@/components/ui/panel";
import { CategoryStrip } from "@/components/ui/score-bar";
import { EmptyState, ErrorState } from "@/components/ui/states";
import { Table, Td, Th, THead, Tr } from "@/components/ui/table";
import { api, ApiError } from "@/lib/api";
import { num, relTime, segment, titleCase } from "@/lib/format";
import type { AccountRow, Paged } from "@/lib/types";
import { cn } from "@/lib/utils";

export const metadata = { title: "Accounts" };

type Search = Record<string, string | string[] | undefined>;

const GRADES = ["A", "B", "C", "D", "X"];
const SEGMENTS = ["strategic", "enterprise", "mid_market", "smb"];
const REGIONS = ["NA", "EMEA", "APAC", "LATAM"];
const STAGES = ["prospect", "contacted", "engaged", "qualified", "meeting", "opportunity", "won", "lost"];
const SORTS: [string, string][] = [
  ["score", "ICP score"],
  ["intent", "Intent"],
  ["recent_signal", "Latest signal"],
  ["employees", "Employees"],
  ["name", "Name"],
];

function list(v: string | string[] | undefined): string[] {
  return v === undefined ? [] : Array.isArray(v) ? v : [v];
}

function toQuery(sp: Search, patch: Record<string, string | string[] | null>): string {
  const q = new URLSearchParams();
  const merged: Record<string, string | string[] | null | undefined> = { ...sp, ...patch };
  for (const [k, v] of Object.entries(merged)) {
    if (v === null || v === undefined || v === "") continue;
    for (const item of list(v)) q.append(k, item);
  }
  const s = q.toString();
  return s ? `?${s}` : "";
}

function Chip({ href, active, children }: { href: string; active: boolean; children: React.ReactNode }) {
  return (
    <Link
      href={href}
      aria-pressed={active}
      className={cn(
        "rounded border px-2 py-0.5 text-xs transition-colors",
        active ? "border-accent bg-accent-soft text-accent-text" : "border-border text-muted hover:text-text",
      )}
    >
      {children}
    </Link>
  );
}

function ToggleChips({ sp, name, values, label }: { sp: Search; name: string; values: string[]; label: (v: string) => string }) {
  const current = list(sp[name]);
  return (
    <div className="flex flex-wrap items-center gap-1">
      {values.map((v) => {
        const on = current.includes(v);
        const next = on ? current.filter((x) => x !== v) : [...current, v];
        return (
          <Chip key={v} href={`/accounts${toQuery(sp, { [name]: next, page: null })}`} active={on}>
            {label(v)}
          </Chip>
        );
      })}
    </div>
  );
}

export default async function AccountsPage(props: PageProps<"/accounts">) {
  const sp = (await props.searchParams) as Search;
  const page = Number(sp.page ?? 1) || 1;
  const qs = toQuery(sp, { page_size: "50", page: String(page) });
  let data: Paged<AccountRow> | null = null;
  let error: string | null = null;
  try {
    data = await api<Paged<AccountRow>>(`/accounts${qs}`);
  } catch (e) {
    error = e instanceof ApiError ? e.message : "Failed to load accounts";
  }
  const pages = data ? Math.max(1, Math.ceil(data.total / data.page_size)) : 1;
  const sort = (sp.sort as string) ?? "score";

  return (
    <div className="space-y-4">
      <PageHeader
        title="Accounts"
        eyebrow={<DemoBadge />}
        description="Every account scored against the active ICP. The score is explainable: fit, intent, timing, technical and engagement points each trace to a rule and its evidence."
      />

      <Panel bodyClassName="space-y-3">
        <form className="flex flex-wrap items-center gap-2" action="/accounts">
          <label className="sr-only" htmlFor="q">
            Search accounts
          </label>
          <input
            id="q"
            name="q"
            defaultValue={(sp.q as string) ?? ""}
            placeholder="Search name or domain"
            className="h-8 w-64 rounded-md border border-border bg-panel px-2.5 text-sm placeholder:text-subtle"
          />
          {list(sp.grade).map((g) => (
            <input key={g} type="hidden" name="grade" value={g} />
          ))}
          <button type="submit" className="h-8 rounded-md border border-border px-3 text-sm hover:bg-panel-2">
            Search
          </button>
          <div className="ml-auto flex flex-wrap items-center gap-1 text-xs text-muted">
            Sort
            {SORTS.map(([key, label]) => (
              <Chip key={key} href={`/accounts${toQuery(sp, { sort: key, page: null })}`} active={sort === key}>
                {label}
              </Chip>
            ))}
          </div>
        </form>
        <div className="grid gap-2 text-xs sm:grid-cols-[80px_1fr]">
          <span className="text-muted">Grade</span>
          <ToggleChips sp={sp} name="grade" values={GRADES} label={(v) => v} />
          <span className="text-muted">Segment</span>
          <ToggleChips sp={sp} name="segment" values={SEGMENTS} label={segment} />
          <span className="text-muted">Region</span>
          <ToggleChips sp={sp} name="region" values={REGIONS} label={(v) => v} />
          <span className="text-muted">Stage</span>
          <ToggleChips sp={sp} name="stage" values={STAGES} label={titleCase} />
          <span className="text-muted">Other</span>
          <div className="flex flex-wrap gap-1">
            <Chip href={`/accounts${toQuery(sp, { unowned: sp.unowned ? null : "true", page: null })}`} active={!!sp.unowned}>
              Unowned
            </Chip>
            <Chip
              href={`/accounts${toQuery(sp, { signal_days: sp.signal_days ? null : "14", page: null })}`}
              active={!!sp.signal_days}
            >
              Signal in last 14 days
            </Chip>
            <Chip
              href={`/accounts${toQuery(sp, { customers: sp.customers === "exclude" ? null : "exclude", page: null })}`}
              active={sp.customers === "exclude"}
            >
              Exclude customers
            </Chip>
            <Link href="/accounts" className="px-2 py-0.5 text-xs text-accent-text hover:underline">
              Reset
            </Link>
          </div>
        </div>
      </Panel>

      {error && <ErrorState message={error} />}
      {data && (
        <Panel
          bodyClassName="p-0"
          title={`${num(data.total)} accounts`}
          description="Bars: fit · intent · timing · technical · engagement"
        >
          {data.items.length === 0 ? (
            <EmptyState title="No accounts match these filters" description="Try removing a filter." />
          ) : (
            <Table>
              <THead>
                <tr>
                  <Th>Account</Th>
                  <Th>Score</Th>
                  <Th>Breakdown</Th>
                  <Th align="right">Intent</Th>
                  <Th>Segment</Th>
                  <Th>Region</Th>
                  <Th>Stage</Th>
                  <Th>Owner</Th>
                  <Th>Latest signal</Th>
                </tr>
              </THead>
              <tbody>
                {data.items.map((a) => (
                  <Tr key={a.id}>
                    <Td className="min-w-48">
                      <Link href={`/accounts/${a.id}`} className="font-medium hover:underline">
                        {a.name}
                      </Link>
                      {a.is_flagship && (
                        <Badge tone="accent" className="ml-1.5">
                          Flagship
                        </Badge>
                      )}
                      <div className="text-xs text-muted">
                        {a.domain ?? <span className="text-warning">No domain</span>} · {a.industry ?? "Unknown industry"}
                      </div>
                    </Td>
                    <Td>
                      <GradeBadge grade={a.score_grade} score={a.icp_score} />
                    </Td>
                    <Td>
                      <CategoryStrip categories={a.categories as unknown as Record<string, number> | null} max={data.category_max} />
                    </Td>
                    <Td align="right">{a.intent_score ?? "—"}</Td>
                    <Td className="whitespace-nowrap text-xs">
                      {segment(a.segment)}
                      <div className="tabular text-muted">{a.employee_count ? `${num(a.employee_count)} emp.` : "Size unknown"}</div>
                    </Td>
                    <Td className="text-xs">{a.region ?? "—"}</Td>
                    <Td className="text-xs">{a.is_customer ? <Badge tone="success">Customer</Badge> : titleCase(a.funnel_stage)}</Td>
                    <Td className="whitespace-nowrap text-xs">{a.owner ?? <span className="text-warning">Unowned</span>}</Td>
                    <Td className="max-w-60 text-xs">
                      <div className="truncate">{a.last_signal?.title ?? "—"}</div>
                      <div className="text-muted">{relTime(a.last_signal_at)}</div>
                    </Td>
                  </Tr>
                ))}
              </tbody>
            </Table>
          )}
          <div className="flex items-center justify-between border-t border-border px-4 py-2 text-xs text-muted">
            <span>
              Page {page} of {pages}
            </span>
            <div className="flex gap-2">
              {page > 1 && (
                <Link className="hover:text-text" href={`/accounts${toQuery(sp, { page: String(page - 1) })}`}>
                  Previous
                </Link>
              )}
              {page < pages && (
                <Link className="hover:text-text" href={`/accounts${toQuery(sp, { page: String(page + 1) })}`}>
                  Next
                </Link>
              )}
            </div>
          </div>
        </Panel>
      )}
    </div>
  );
}
