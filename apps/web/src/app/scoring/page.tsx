import { DemoBadge } from "@/components/ui/badge";
import { PageHeader } from "@/components/ui/page-header";
import { Panel } from "@/components/ui/panel";
import { ScoreBar } from "@/components/ui/score-bar";
import { ErrorState } from "@/components/ui/states";
import { Table, Td, Th, THead, Tr } from "@/components/ui/table";
import type { ICPResponse, SignalType, Weights } from "@/components/insights/types";
import { api, ApiError } from "@/lib/api";
import { dateTime, num, pct, titleCase } from "@/lib/format";

import { EvaluationPanel } from "./evaluation-panel";
import type { ScoringEvaluation } from "./evaluation-types";
import { IcpEditor } from "./icp-editor";

export const metadata = { title: "ICP & Scoring" };

const CATEGORY_COPY: Record<keyof Weights, string> = {
  fit: "Industry, company size and geography against the ICP.",
  intent: "Buying signals: hiring surges, launches, relevant postings, tech adoption, pricing visits.",
  timing: "Funding, executive hires, expansion, and headcount growth.",
  technical: "AI/ML team size, LLM stack and platform stack compatibility.",
  engagement: "Product usage and sales engagement with us.",
};

function Tags({ items, tone = "neutral" }: { items: string[]; tone?: "neutral" | "danger" | "accent" }) {
  if (!items.length) return <span className="text-xs text-subtle">None</span>;
  const cls =
    tone === "danger"
      ? "border-transparent bg-danger-soft text-danger"
      : tone === "accent"
        ? "border-transparent bg-accent-soft text-accent-text"
        : "border-border bg-panel-2 text-text";
  return (
    <span className="flex flex-wrap gap-1">
      {items.map((i) => (
        <span key={i} className={`rounded border px-1.5 py-0.5 text-[11px] ${cls}`}>
          {i}
        </span>
      ))}
    </span>
  );
}

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="grid gap-1 border-b border-border py-2.5 last:border-0 sm:grid-cols-[10rem_1fr] sm:gap-3">
      <dt className="text-xs text-muted">{label}</dt>
      <dd className="min-w-0 text-sm text-text">{children}</dd>
    </div>
  );
}

/** Employee-count band drawn on a log scale so 25 → 10,000 fits in one line. */
function SizeBand({ size }: { size: ICPResponse["definition"]["size"] }) {
  const lo = Math.log10(10);
  const hi = Math.log10(Math.max(size.max_employees * 2, 20000));
  const x = (v: number) => `${((Math.log10(Math.max(v, 10)) - lo) / (hi - lo)) * 100}%`;
  return (
    <div className="space-y-1.5">
      <div className="relative h-3 rounded-full bg-panel-2" role="img" aria-label={`Employee band ${size.min_employees} to ${size.max_employees}, sweet spot ${size.sweet_spot_min} to ${size.sweet_spot_max}, excluded below ${size.hard_min_employees}`}>
        <div className="absolute inset-y-0 left-0 rounded-l-full bg-danger-soft" style={{ width: x(size.hard_min_employees) }} />
        <div className="absolute inset-y-0 bg-accent/25" style={{ left: x(size.min_employees), width: `calc(${x(size.max_employees)} - ${x(size.min_employees)})` }} />
        <div className="absolute inset-y-0 bg-accent" style={{ left: x(size.sweet_spot_min), width: `calc(${x(size.sweet_spot_max)} - ${x(size.sweet_spot_min)})` }} />
      </div>
      <div className="flex flex-wrap gap-x-4 gap-y-1 text-[11px] text-muted">
        <span>
          <span className="mr-1 inline-block size-2 rounded-sm bg-accent align-middle" />
          Sweet spot {num(size.sweet_spot_min)}–{num(size.sweet_spot_max)}
        </span>
        <span>
          <span className="mr-1 inline-block size-2 rounded-sm bg-accent/25 align-middle" />
          In range {num(size.min_employees)}–{num(size.max_employees)}
        </span>
        <span>
          <span className="mr-1 inline-block size-2 rounded-sm bg-danger-soft align-middle" />
          Excluded below {num(size.hard_min_employees)}
        </span>
      </div>
    </div>
  );
}

export default async function ScoringPage() {
  let icp: ICPResponse | null = null;
  let error: string | null = null;
  try {
    icp = await api<ICPResponse>("/icp");
  } catch (e) {
    error = e instanceof ApiError ? e.message : "Failed to load the ICP";
  }
  // The backtest is supporting evidence: if it fails, the page still explains the model.
  const evaluation = await api<ScoringEvaluation>("/analytics/scoring-evaluation").catch(() => null);

  const header = (
    <PageHeader
      title="ICP & scoring model"
      eyebrow={icp ? <span className="inline-flex items-center gap-2">Active ICP v{icp.version} <DemoBadge /></span> : undefined}
      description="Who we sell to, and how every account earns its score. The model is deterministic and explainable: each point traces to a rule, a signal, and its evidence."
    />
  );
  if (!icp) {
    return (
      <div>
        {header}
        <ErrorState title="Couldn't load the ICP" message={error ?? undefined} />
      </div>
    );
  }

  const d = icp.definition;
  const signalsByCategory = icp.signal_types.reduce<Record<string, SignalType[]>>((acc, s) => {
    (acc[s.category] ??= []).push(s);
    return acc;
  }, {});
  const categories = Object.keys(d.weights) as (keyof Weights)[];

  return (
    <div className="space-y-6">
      {header}

      <div className="grid gap-4 lg:grid-cols-3">
        <Panel title={d.name} description={d.description} className="lg:col-span-2">
          <dl>
            <Row label="Core industries">
              <Tags items={d.core_industries} tone="accent" />
            </Row>
            <Row label="Adjacent industries">
              <Tags items={d.adjacent_industries} />
            </Row>
            <Row label="Company size">
              <SizeBand size={d.size} />
            </Row>
            <Row label="Regions">
              <span className="flex flex-wrap items-center gap-2 text-xs">
                <span className="text-muted">Primary</span>
                <Tags items={d.primary_regions} tone="accent" />
                <span className="text-muted">Secondary</span>
                <Tags items={d.secondary_regions} />
              </span>
            </Row>
            <Row label="Funding stages">
              <Tags items={d.funding_stages} />
              <p className="mt-1 text-[11px] text-muted">Informational; timing points come from funding signals. Min. headcount growth {pct(d.min_growth_rate, 0)}.</p>
            </Row>
            <Row label="AI/ML team">
              <span className="text-xs">
                At least <span className="tabular font-medium">{num(d.technical.ai_team_min)}</span> people; strong at{" "}
                <span className="tabular font-medium">{num(d.technical.ai_team_strong)}+</span>
              </span>
            </Row>
            <Row label="LLM stack">
              <Tags items={d.technical.llm_stack} />
            </Row>
            <Row label="Platform stack">
              <Tags items={d.technical.platform_stack} />
            </Row>
            <Row label="Buyer personas">
              <Tags items={d.buyer_personas} />
            </Row>
            <Row label="Exclusions (grade X)">
              <div className="space-y-1.5 text-xs">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="w-16 text-muted">Industries</span>
                  <Tags items={d.excluded_industries} tone="danger" />
                </div>
                <div className="flex flex-wrap items-center gap-2">
                  <span className="w-16 text-muted">Countries</span>
                  <Tags items={d.excluded_countries} tone="danger" />
                </div>
                <div className="flex flex-wrap items-center gap-2">
                  <span className="w-16 text-muted">Domains</span>
                  <Tags items={d.excluded_domains} tone="danger" />
                </div>
              </div>
            </Row>
          </dl>
        </Panel>

        <div className="space-y-4">
          <Panel title="Category weights" description="Points available per category · always sums to 100">
            <ul className="space-y-3">
              {categories.map((c) => (
                <li key={c}>
                  <div className="flex items-baseline justify-between text-xs">
                    <span className="font-medium text-text">{titleCase(c)}</span>
                    <span className="tabular font-semibold text-text">{num(d.weights[c], 1)}</span>
                  </div>
                  <ScoreBar value={d.weights[c]} max={100} className="mt-1" />
                  <p className="mt-1 text-[11px] text-muted">{CATEGORY_COPY[c]}</p>
                </li>
              ))}
            </ul>
          </Panel>

          <Panel title="Versions" bodyClassName="p-0">
            <ul className="divide-y divide-border text-xs">
              {[...icp.versions].sort((a, b) => b.version - a.version).map((v) => (
                <li key={v.version} className="flex items-center justify-between gap-2 px-4 py-2">
                  <span>
                    <span className="font-medium text-text">v{v.version}</span>
                    <span className="text-muted"> · {v.created_by}</span>
                  </span>
                  <span className="flex items-center gap-2 text-muted">
                    {dateTime(v.created_at)}
                    {v.is_active && <span className="rounded bg-success-soft px-1.5 py-0.5 text-[11px] font-medium text-success">active</span>}
                  </span>
                </li>
              ))}
            </ul>
          </Panel>
        </div>
      </div>

      <Panel title="Signal point budgets" description="Max points each signal type can contribute inside its category, and how fast it decays" bodyClassName="p-0">
        <Table>
          <THead>
            <tr>
              <Th>Signal</Th>
              <Th>Category</Th>
              <Th align="right">Max points</Th>
              <Th align="right">Typical strength</Th>
              <Th align="right">Half-life</Th>
              <Th>What it means</Th>
            </tr>
          </THead>
          <tbody>
            {categories
              .filter((c) => signalsByCategory[c])
              .flatMap((c) => {
                const types = signalsByCategory[c];
                const budget = types.reduce((acc, s) => acc + (d.positive_signals[s.key] ?? 0), 0);
                return [
                  <tr key={`h-${c}`} className="border-b border-border bg-panel-2/60">
                    <td colSpan={6} className="px-3 py-1.5 text-[11px] text-muted">
                      <span className="font-medium uppercase tracking-wide text-text">{c}</span> · signal points total{" "}
                      <span className="tabular font-medium text-text">{num(budget, 1)}</span>, capped at the category budget of{" "}
                      <span className="tabular font-medium text-text">{num(d.weights[c], 1)}</span>
                      {c !== "intent" && " (shared with non-signal rules)"}
                    </td>
                  </tr>,
                  ...types.map((s) => {
                    const pts = d.positive_signals[s.key] ?? 0;
                    return (
                      <Tr key={s.key}>
                        <Td className="whitespace-nowrap font-medium">{s.name}</Td>
                        <Td className="text-xs text-muted">{titleCase(s.category)}</Td>
                        <Td align="right" className={pts ? undefined : "text-subtle"}>
                          {pts ? num(pts, 1) : "ignored"}
                        </Td>
                        <Td align="right">{s.default_strength.toFixed(2)}</Td>
                        <Td align="right">{num(s.half_life_days)} d</Td>
                        <Td className="min-w-64 text-xs text-muted">{s.description}</Td>
                      </Tr>
                    );
                  }),
                ];
              })}
          </tbody>
        </Table>
      </Panel>

      <Panel title="How a score is computed">
        <div className="grid gap-6 text-xs md:grid-cols-2">
          <ol className="list-decimal space-y-2 pl-4 text-text marker:text-muted">
            <li>
              <span className="font-medium">Category budgets.</span> Fit, intent, timing, technical and engagement each get the weight above
              as their maximum points; the five sum to 100. A category never exceeds its budget, however many rules fire.
            </li>
            <li>
              <span className="font-medium">Rules inside a category.</span> Fit splits into industry, size and geography; technical into AI
              team, LLM stack and platform stack. Shares rescale when weights change.
            </li>
            <li>
              <span className="font-medium">Signals.</span> Each signal type can earn up to its max points. The strongest signal of a type
              counts in full; each additional signal of the same type adds 25% of its value (capped at the type&apos;s max).
            </li>
            <li>
              <span className="font-medium">Exclusions.</span> Excluded industries, countries, domains, or headcount below the hard minimum
              force a score of 0 and grade <span className="font-semibold">X</span>, whatever the signals say.
            </li>
          </ol>
          <div className="space-y-3">
            <div className="rounded-md border border-border bg-panel-2 p-3 font-mono text-[11px] leading-relaxed text-text">
              <div>signal value = min(1, confidence × relative strength × 0.5^(age ÷ half-life))</div>
              <div className="text-muted">relative strength = min(strength ÷ typical strength, 1.25)</div>
              <div className="mt-1.5">type points = max points × min(1, best + 0.25 × Σ others)</div>
              <div className="mt-1.5">score = Σ min(category points, category budget)</div>
            </div>
            <div>
              <div className="mb-1 text-[11px] font-medium uppercase tracking-wide text-muted">Grades</div>
              <div className="grid grid-cols-5 gap-1 text-center text-[11px]">
                <div className="rounded bg-success-soft py-1 text-success"><span className="font-semibold">A</span> ≥ 72</div>
                <div className="rounded bg-info-soft py-1 text-info"><span className="font-semibold">B</span> ≥ 58</div>
                <div className="rounded bg-warning-soft py-1 text-warning"><span className="font-semibold">C</span> ≥ 45</div>
                <div className="rounded bg-panel-2 py-1 text-muted"><span className="font-semibold">D</span> &lt; 45</div>
                <div className="rounded bg-danger-soft py-1 text-danger"><span className="font-semibold">X</span> excluded</div>
              </div>
            </div>
            <p className="text-muted">
              Same inputs always produce the same score. A 90-day half-life means a funding round is worth half its points after three
              months and a quarter after six. Band boundaries come from the score distribution and how much a team can work, not from
              round numbers — the panel below shows whether they order conversion correctly.
            </p>
          </div>
        </div>
      </Panel>

      <EvaluationPanel evaluation={evaluation} />

      <IcpEditor initial={d} signalTypes={icp.signal_types} version={icp.version} />
    </div>
  );
}
