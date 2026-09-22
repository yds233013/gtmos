import { X } from "lucide-react";
import Link from "next/link";

import { AutoSubmitSelect } from "@/components/revenue/filter-controls";
import { Pagination } from "@/components/revenue/pagination";
import { apiQuery, first, hrefWith, intParam, oneOf } from "@/components/revenue/query";
import { Badge, DemoBadge, GradeBadge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { PageHeader } from "@/components/ui/page-header";
import { Panel } from "@/components/ui/panel";
import { ScoreBar } from "@/components/ui/score-bar";
import { EmptyState, ErrorState } from "@/components/ui/states";
import { Table, Td, Th, THead, Tr } from "@/components/ui/table";
import { api, settle } from "@/lib/api";
import { dateTime, num, pct, relTime, titleCase } from "@/lib/format";
import type { Signal } from "@/lib/types";
import { cn } from "@/lib/utils";

import type { SignalFeed, SignalType } from "./types";

export const metadata = { title: "Signals" };

const BASE = "/signals";
const PAGE_SIZE = 25;
const WINDOWS = ["7", "14", "30", "90"] as const;
const CONFIDENCE = ["0.5", "0.7", "0.8", "0.9"] as const;
const GRADES = ["A", "B", "C", "D", "X"] as const;

/** Mirrors gtmos.domain.scoring.signal_value: confidence × relative strength × half-life decay. */
function valueNow(s: Signal, spec: SignalType | undefined, now: number = Date.now()): number | null {
  if (!spec) return null;
  const ageDays = Math.max(0, (now - new Date(s.observed_at).getTime()) / 86_400_000);
  const relative = spec.default_strength > 0 ? Math.min(s.strength / spec.default_strength, 1.25) : 1;
  return Math.min(1, s.confidence * relative * Math.pow(0.5, ageDays / spec.half_life_days));
}

export default async function SignalsPage(props: PageProps<"/signals">) {
  const sp = await props.searchParams;
  const days = oneOf(sp.days, WINDOWS) ?? "30";
  const minConfidence = oneOf(sp.min_confidence, CONFIDENCE);
  const grade = oneOf(sp.grade, GRADES);
  const type = first(sp.type);
  const source = first(sp.source);
  const page = intParam(sp.page, 1);

  const current = { days, type, min_confidence: minConfidence, grade, source };
  const common = { days, min_confidence: minConfidence, grade, source };

  const [types, feed, unfiltered] = await settle(
    api<SignalType[]>("/signal-types"),
    api<SignalFeed>(`/signals?${apiQuery({ ...common, type, page, page_size: PAGE_SIZE })}`),
    // Chip counts ignore the type filter so every type stays one click away.
    type ? api<SignalFeed>(`/signals?${apiQuery({ ...common, page_size: 1 })}`) : Promise.resolve(null),
  );

  if (!feed) {
    return (
      <div>
        <PageHeader title="Signals" description="Timestamped buying signals from every connected source." />
        <ErrorState title="Couldn't load the signal feed" message="The GTMOS API did not respond. Check that the backend is running." />
      </div>
    );
  }

  const typeMap = new Map((types ?? []).map((t) => [t.key, t]));
  const chipCounts = Object.entries((unfiltered ?? feed).by_type).sort((a, b) => b[1] - a[1]);
  const chipTotal = chipCounts.reduce((sum, [, n]) => sum + n, 0);
  const hasDemo = feed.items.some((s) => s.data_origin === "demo");
  const filtered = Boolean(type || minConfidence || grade || source);
  const typeOptions = [
    { value: "", label: "All types" },
    ...(types ?? [])
      .slice()
      .sort((a, b) => a.name.localeCompare(b.name))
      .map((t) => ({ value: t.key, label: t.name })),
  ];

  return (
    <div className="space-y-4">
      <PageHeader
        title="Signals"
        eyebrow={
          <span className="inline-flex items-center gap-2">
            Last {days} days · {num(feed.total)} signals {hasDemo && <DemoBadge />}
          </span>
        }
        description="Every timestamped buying signal GTMOS has observed: hiring surges, launches, funding, product usage and web intent. Signals decay over time, feed the ICP and intent score, and can trigger workflows."
      />

      <Panel bodyClassName="flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
        <div className="flex flex-col gap-1">
          <span className="text-[11px] font-medium text-muted" id="window-label">
            Time window
          </span>
          <div role="group" aria-labelledby="window-label" className="inline-flex w-fit rounded-md border border-border p-0.5">
            {WINDOWS.map((w) => (
              <Link
                key={w}
                href={hrefWith(BASE, current, { days: w })}
                aria-current={w === days ? "page" : undefined}
                className={cn(
                  "tabular rounded px-2.5 py-1 text-xs font-medium",
                  w === days ? "bg-accent-soft text-accent-text" : "text-muted hover:bg-panel-2 hover:text-text",
                )}
              >
                {w}d
              </Link>
            ))}
          </div>
        </div>

        <form method="get" action={BASE} className="grid grid-cols-2 gap-3 sm:flex sm:flex-wrap sm:items-end">
          <input type="hidden" name="days" value={days} />
          {source && <input type="hidden" name="source" value={source} />}
          <AutoSubmitSelect name="type" label="Signal type" value={type} options={typeOptions} className="col-span-2 sm:w-48" />
          <AutoSubmitSelect
            name="min_confidence"
            label="Min confidence"
            value={minConfidence}
            options={[{ value: "", label: "Any" }, ...CONFIDENCE.map((c) => ({ value: c, label: `≥ ${pct(Number(c), 0)}` }))]}
            className="sm:w-32"
          />
          <AutoSubmitSelect
            name="grade"
            label="Account grade"
            value={grade}
            options={[{ value: "", label: "All grades" }, ...GRADES.map((g) => ({ value: g, label: `Grade ${g}` }))]}
            className="sm:w-32"
          />
          <div className="col-span-2 flex items-center gap-2 sm:col-span-1">
            <Button type="submit" size="md" variant="secondary">
              Apply
            </Button>
            {filtered && (
              <Link href={hrefWith(BASE, { days })} className="text-xs text-accent-text hover:underline">
                Reset
              </Link>
            )}
          </div>
        </form>
      </Panel>

      {chipCounts.length > 0 && (
        <nav aria-label="Signals by type" className="flex flex-wrap gap-1.5">
          <Link
            href={hrefWith(BASE, current, { type: null })}
            aria-current={!type ? "page" : undefined}
            className={cn(chipCls, !type && chipActive)}
          >
            All <span className="tabular text-subtle">{num(chipTotal)}</span>
          </Link>
          {chipCounts.map(([key, n]) => (
            <Link
              key={key}
              href={hrefWith(BASE, current, { type: key })}
              aria-current={type === key ? "page" : undefined}
              className={cn(chipCls, type === key && chipActive)}
            >
              {typeMap.get(key)?.name ?? titleCase(key)} <span className="tabular text-subtle">{num(n)}</span>
            </Link>
          ))}
        </nav>
      )}

      {source && (
        <div className="flex items-center gap-2 text-xs text-muted">
          Filtered to source
          <Link
            href={hrefWith(BASE, current, { source: null })}
            className="inline-flex items-center gap-1 rounded border border-border bg-panel px-1.5 py-0.5 font-mono text-[11px] text-text hover:bg-panel-2"
            aria-label={`Remove source filter ${source}`}
          >
            {source} <X className="size-3" aria-hidden />
          </Link>
        </div>
      )}

      <div className="grid grid-cols-1 gap-4 xl:grid-cols-4">
        <Panel
          title="Feed"
          description="Newest first · value now = confidence × relative strength × half-life decay"
          className="min-w-0 xl:col-span-3"
          bodyClassName="p-0"
        >
          {feed.items.length === 0 ? (
            <EmptyState
              title="No signals match these filters"
              description={`Nothing was observed in the last ${days} days with these filters. Widen the time window or lower the confidence threshold.`}
              action={
                <Link href={hrefWith(BASE, { days: "90" })} className="text-xs text-accent-text hover:underline">
                  Show all signals from the last 90 days
                </Link>
              }
            />
          ) : (
            <>
              <Table>
                <THead>
                  <tr>
                    <Th>Observed</Th>
                    <Th>Account</Th>
                    <Th>Signal</Th>
                    <Th>Source</Th>
                    <Th align="right">Conf.</Th>
                    <Th align="right">Strength</Th>
                    <Th className="w-28">Value now</Th>
                  </tr>
                </THead>
                <tbody>
                  {feed.items.map((s) => {
                    const spec = typeMap.get(s.signal_type);
                    const value = valueNow(s, spec);
                    return (
                      <Tr key={s.id}>
                        <Td className="whitespace-nowrap align-top text-xs text-muted" title={dateTime(s.observed_at)}>
                          <time dateTime={s.observed_at}>{relTime(s.observed_at)}</time>
                        </Td>
                        <Td className="align-top">
                          <div className="flex items-center gap-2">
                            <Link href={`/accounts/${s.account_id}`} className="whitespace-nowrap font-medium hover:underline">
                              {s.account_name ?? "Unknown account"}
                            </Link>
                          </div>
                          <div className="mt-1">
                            <GradeBadge grade={s.account_grade} score={s.account_score} />
                          </div>
                        </Td>
                        <Td className="min-w-72 max-w-xl align-top">
                          <div className="flex flex-wrap items-center gap-1.5">
                            <Badge tone="accent">{spec?.name ?? titleCase(s.signal_type)}</Badge>
                            {s.category && <span className="text-[11px] text-muted">{titleCase(s.category)}</span>}
                            {s.data_origin === "demo" && <DemoBadge />}
                          </div>
                          <div className="mt-1 font-medium text-text">
                            {s.source_url ? (
                              <a href={s.source_url} target="_blank" rel="noreferrer" className="hover:underline">
                                {s.title}
                              </a>
                            ) : (
                              s.title
                            )}
                          </div>
                          <p className="mt-0.5 line-clamp-2 text-xs text-muted" title={s.explanation}>
                            {s.explanation}
                          </p>
                        </Td>
                        <Td className="align-top">
                          <Link
                            href={hrefWith(BASE, current, { source: s.source })}
                            className="whitespace-nowrap font-mono text-[11px] text-muted hover:text-text hover:underline"
                            title={`Only show signals from ${s.source}`}
                          >
                            {s.source}
                          </Link>
                        </Td>
                        <Td align="right" className="align-top text-xs">
                          {pct(s.confidence, 0)}
                        </Td>
                        <Td align="right" className="align-top text-xs" title={spec ? `Typical for this type: ${spec.default_strength.toFixed(2)}` : undefined}>
                          {s.strength.toFixed(2)}
                        </Td>
                        <Td className="align-top">
                          {value === null ? (
                            <span className="text-xs text-subtle">—</span>
                          ) : (
                            <div title={spec ? `${spec.half_life_days}-day half-life` : undefined}>
                              <div className="tabular text-xs text-text">{pct(value, 0)}</div>
                              <ScoreBar value={value} max={1} className="mt-1" tone={value < 0.25 ? "muted" : "accent"} />
                            </div>
                          )}
                        </Td>
                      </Tr>
                    );
                  })}
                </tbody>
              </Table>
              <Pagination base={BASE} params={current} page={page} pageSize={PAGE_SIZE} total={feed.total} noun="signals" />
            </>
          )}
        </Panel>

        <div className="space-y-4">
          <Panel title="How signals work">
            <div className="space-y-3 text-xs leading-relaxed text-muted">
              <p>
                <span className="font-medium text-text">A signal</span> is a timestamped, sourced event that suggests an
                account may be ready to buy: an AI hiring surge, a product launch, a funding round, a pricing-page visit.
                Every signal keeps its source, confidence and evidence.
              </p>
              <p>
                <span className="font-medium text-text">Half-life decay.</span> A signal&apos;s weight halves every N days
                (set per type), so a launch from yesterday outweighs one from last quarter. Value now = confidence ×
                strength relative to what is typical for the type × 0.5<sup>age / half-life</sup>.
              </p>
              <p>
                <span className="font-medium text-text">What they drive.</span> Signals feed the intent and timing
                categories of the ICP score, and new signals can trigger workflows (research, drafting, routing) with a
                human approving anything outbound.
              </p>
            </div>
          </Panel>

          {types && types.length > 0 && (
            <Panel title="Signal types" description="Category and half-life per type" bodyClassName="p-0">
              <ul className="divide-y divide-border">
                {types
                  .slice()
                  .sort((a, b) => a.half_life_days - b.half_life_days)
                  .map((t) => (
                    <li key={t.key} className="flex items-start justify-between gap-3 px-4 py-2 text-xs" title={t.description}>
                      <div className="min-w-0">
                        <Link href={hrefWith(BASE, current, { type: t.key })} className="font-medium text-text hover:underline">
                          {t.name}
                        </Link>
                        <div className="text-[11px] text-muted">{titleCase(t.category)}</div>
                      </div>
                      <span className="tabular shrink-0 text-muted">{t.half_life_days}d</span>
                    </li>
                  ))}
              </ul>
            </Panel>
          )}
        </div>
      </div>
    </div>
  );
}

const chipCls =
  "inline-flex items-center gap-1.5 rounded-md border border-border bg-panel px-2 py-1 text-xs text-text hover:bg-panel-2";
const chipActive = "border-transparent bg-accent-soft text-accent-text hover:bg-accent-soft";
