import { ArrowLeft, Info } from "lucide-react";
import Link from "next/link";
import { notFound } from "next/navigation";
import { cache } from "react";

import {
  IntervalAxis,
  IntervalBar,
  metricLabel,
  niceMax,
  pp,
  pValue,
  signedPct,
  VerdictBadge,
  verdictMeta,
} from "@/components/insights/experiment-ui";
import type { Comparison, ExperimentDetail, Variant } from "@/components/insights/types";
import { Badge, DemoBadge } from "@/components/ui/badge";
import { PageHeader } from "@/components/ui/page-header";
import { Panel } from "@/components/ui/panel";
import { ScoreBar } from "@/components/ui/score-bar";
import { ErrorState } from "@/components/ui/states";
import { Table, Td, Th, THead, Tr } from "@/components/ui/table";
import { api, ApiError } from "@/lib/api";
import { date, money, num, pct } from "@/lib/format";
import { cn } from "@/lib/utils";

const METRIC_ORDER = ["reply", "positive_reply", "meeting", "opportunity"];

/** Deduped per request so generateMetadata and the page share one API call. */
const fetchExperiment = cache((key: string) => api<ExperimentDetail>(`/experiments/${encodeURIComponent(key)}`));

async function load(key: string): Promise<{ exp: ExperimentDetail | null; error: string | null }> {
  try {
    return { exp: await fetchExperiment(key), error: null };
  } catch (e) {
    if (e instanceof ApiError && e.status === 404) notFound();
    return { exp: null, error: e instanceof ApiError ? e.message : "Failed to load the experiment" };
  }
}

export async function generateMetadata(props: PageProps<"/experiments/[key]">) {
  const { key } = await props.params;
  try {
    const exp = await fetchExperiment(key);
    return { title: `${exp.name} · Experiment` };
  } catch {
    return { title: "Experiment" };
  }
}

function ComparisonTable({
  control,
  treatment,
  comps,
  primary,
}: {
  control: Variant;
  treatment: Variant;
  comps: Record<string, Comparison>;
  primary: string;
}) {
  const metrics = [...METRIC_ORDER.filter((m) => comps[m] || control.metrics[m]), ...Object.keys(comps).filter((m) => !METRIC_ORDER.includes(m))];
  const scaleMax = niceMax(
    Math.max(
      ...metrics.flatMap((m) => [control.metrics[m]?.ci_high ?? 0, treatment.metrics[m]?.ci_high ?? 0]),
      0.05,
    ),
  );
  return (
    <Table>
      <THead>
        <tr>
          <Th>Metric</Th>
          <Th align="right">Control</Th>
          <Th align="right">Treatment</Th>
          <Th className="min-w-48">
            <span className="block">Rate with 95% CI</span>
            <IntervalAxis max={scaleMax} />
          </Th>
          <Th align="right">Abs. lift (95% CI)</Th>
          <Th align="right">Rel. lift</Th>
          <Th align="right">p-value</Th>
          <Th>Verdict</Th>
        </tr>
      </THead>
      <tbody>
        {metrics.map((m) => {
          const c = control.metrics[m];
          const t = treatment.metrics[m];
          const cmp = comps[m];
          const isPrimary = m === primary;
          return (
            <Tr key={m} className={cn(isPrimary && "bg-accent-soft/40")}>
              <Td className="align-top">
                <div className="flex flex-wrap items-center gap-1.5 whitespace-nowrap">
                  <span className="font-medium">{metricLabel(m)}</span>
                  {isPrimary && <Badge tone="accent">Primary</Badge>}
                </div>
                {cmp?.required_n_per_variant ? (
                  <div className="mt-0.5 text-[11px] text-muted" title="Per-variant sample needed to detect the observed lift at 95% confidence and 80% power">
                    Needs ~{num(cmp.required_n_per_variant)} / variant to detect this lift
                  </div>
                ) : null}
              </Td>
              <Td align="right" className="align-top">
                <div className="font-medium">{c ? pct(c.rate) : "—"}</div>
                {c && (
                  <div className="text-[11px] text-muted">
                    {num(c.successes)} / {num(c.n)}
                  </div>
                )}
              </Td>
              <Td align="right" className="align-top">
                <div className="font-medium">{t ? pct(t.rate) : "—"}</div>
                {t && (
                  <div className="text-[11px] text-muted">
                    {num(t.successes)} / {num(t.n)}
                  </div>
                )}
              </Td>
              <Td className="align-top">
                <div className="space-y-1.5 py-0.5">
                  {c && <IntervalBar low={c.ci_low} high={c.ci_high} point={c.rate} max={scaleMax} variant="control" label={`Control ${metricLabel(m)}`} />}
                  {t && (
                    <IntervalBar low={t.ci_low} high={t.ci_high} point={t.rate} max={scaleMax} variant="treatment" label={`Treatment ${metricLabel(m)}`} />
                  )}
                </div>
              </Td>
              <Td align="right" className="align-top whitespace-nowrap">
                <div className="font-medium">{pp(cmp?.absolute_lift)}</div>
                <div className="text-[11px] text-muted">
                  {cmp?.diff_ci_low !== null && cmp?.diff_ci_low !== undefined
                    ? `${pp(cmp.diff_ci_low)} to ${pp(cmp.diff_ci_high)}`
                    : "—"}
                </div>
              </Td>
              <Td align="right" className="align-top">
                {signedPct(cmp?.relative_lift)}
              </Td>
              <Td align="right" className="align-top">
                {pValue(cmp?.p_value)}
              </Td>
              <Td className="max-w-64 align-top">
                {cmp ? (
                  <>
                    <VerdictBadge verdict={cmp.verdict} />
                    <p className="mt-1 text-[11px] leading-snug text-muted">{cmp.explanation}</p>
                  </>
                ) : (
                  "—"
                )}
              </Td>
            </Tr>
          );
        })}
      </tbody>
    </Table>
  );
}

export default async function ExperimentPage(props: PageProps<"/experiments/[key]">) {
  const { key } = await props.params;
  const { exp, error } = await load(key);

  if (!exp) {
    return (
      <div className="space-y-4">
        <PageHeader title="Experiment" />
        <ErrorState title="Couldn't load this experiment" message={error ?? undefined} />
      </div>
    );
  }

  const control = exp.variants.find((v) => v.is_control) ?? exp.variants[0];
  const treatments = exp.variants.filter((v) => v !== control);
  const verdict = verdictMeta(exp.verdict);
  const VerdictIcon = verdict.icon;
  const insufficient = exp.verdict === "insufficient_sample" || exp.verdict === "insufficient_events";
  const smallest = Math.min(...exp.variants.map((v) => v.units));

  return (
    <div className="space-y-6">
      <div>
        <Link href="/experiments" className="mb-3 inline-flex items-center gap-1 text-xs text-muted hover:text-text">
          <ArrowLeft className="size-3.5" aria-hidden />
          Experiments
        </Link>
        <PageHeader
          title={exp.name}
          eyebrow={
            <span className="inline-flex flex-wrap items-center gap-2">
              <Badge tone={exp.status === "running" ? "info" : "neutral"}>{exp.status}</Badge>
              {exp.campaign && <span>Campaign: {exp.campaign}</span>}
              <span>
                {date(exp.started_at)} – {exp.ended_at ? date(exp.ended_at) : "running"}
              </span>
              {exp.data_origin !== "live" && <DemoBadge />}
            </span>
          }
          description={`Primary metric: ${metricLabel(exp.primary_metric).toLowerCase()} per ${exp.unit}. Minimum sample ${num(exp.min_sample_per_variant)} ${exp.unit}s per variant, fixed before launch.`}
        />
      </div>

      <section className={cn("rounded-lg border p-4", verdict.box)} aria-labelledby="verdict-heading">
        <div className="flex items-start gap-3">
          <VerdictIcon className={cn("mt-0.5 size-5 shrink-0", verdict.ink)} aria-hidden />
          <div className="min-w-0 flex-1">
            <h2 id="verdict-heading" className={cn("text-base font-semibold", verdict.ink)}>
              {verdict.label}
              <span className="ml-2 text-xs font-normal text-muted">on {metricLabel(exp.primary_metric).toLowerCase()}</span>
            </h2>
            <p className="mt-1 text-sm text-text">{exp.verdict_explanation}</p>
            {insufficient && (
              <p className="mt-1 text-xs text-muted">
                Keep the test running. Observed differences at this sample size are mostly noise, so the dashboard declares no winner.
              </p>
            )}
          </div>
        </div>
      </section>

      <div className="grid gap-4 lg:grid-cols-3">
        <Panel title="Hypothesis" className="lg:col-span-2">
          <dl className="space-y-3 text-sm">
            <div>
              <dt className="text-[11px] font-medium uppercase tracking-wide text-muted">H1 · what we expect</dt>
              <dd className="mt-0.5 text-text">{exp.hypothesis}</dd>
            </div>
            <div>
              <dt className="text-[11px] font-medium uppercase tracking-wide text-muted">H0 · null hypothesis</dt>
              <dd className="mt-0.5 text-text">{exp.null_hypothesis}</dd>
            </div>
            <div>
              <dt className="text-[11px] font-medium uppercase tracking-wide text-muted">Assignment</dt>
              <dd className="mt-0.5 text-xs text-muted">
                Deterministic hash per {exp.unit}; the same {exp.unit} always lands in the same variant, and no one picks who gets
                what.
                <code className="mt-1 block overflow-x-auto rounded border border-border bg-panel-2 px-2 py-1 font-mono text-[11px] text-text">
                  {exp.assignment}
                </code>
              </dd>
            </div>
          </dl>
        </Panel>

        <Panel title="Sample" description={`Pre-registered minimum: ${num(exp.min_sample_per_variant)} per variant`}>
          <ul className="space-y-3">
            {exp.variants.map((v) => {
              const reached = v.units >= exp.min_sample_per_variant;
              return (
                <li key={v.key} className="text-xs">
                  <div className="flex items-baseline justify-between gap-2">
                    <span className="min-w-0 truncate">
                      <span className="font-medium text-text">{v.name}</span>{" "}
                      <span className="text-muted">{v.is_control ? "control" : "treatment"}</span>
                    </span>
                    <span className="tabular shrink-0 text-text">
                      {num(v.units)} / {num(exp.min_sample_per_variant)}
                    </span>
                  </div>
                  <ScoreBar value={v.units} max={exp.min_sample_per_variant} tone={reached ? "success" : "warning"} className="mt-1" />
                  {v.description && <p className="mt-1 text-[11px] text-muted">{v.description}</p>}
                  <p className="mt-0.5 text-[11px] text-muted">
                    Pipeline <span className="tabular font-medium text-text">{money(v.pipeline)}</span>
                  </p>
                </li>
              );
            })}
          </ul>
          {smallest < exp.min_sample_per_variant && (
            <p className="mt-3 text-[11px] text-warning">
              Smallest arm has {num(smallest)} of {num(exp.min_sample_per_variant)} required {exp.unit}s.
            </p>
          )}
        </Panel>
      </div>

      {treatments.map((t) => (
        <Panel
          key={t.key}
          title={`${control.name} vs ${t.name}`}
          description="Per-metric results · rates with 95% Wilson intervals on a shared scale"
          bodyClassName="p-0"
          actions={
            <span className="hidden items-center gap-3 text-[11px] text-muted sm:flex">
              <span className="inline-flex items-center gap-1">
                <span className="size-2 rounded-full bg-muted" aria-hidden /> Control
              </span>
              <span className="inline-flex items-center gap-1">
                <span className="size-2 rounded-full bg-accent" aria-hidden /> Treatment
              </span>
            </span>
          }
        >
          <ComparisonTable control={control} treatment={t} comps={exp.comparisons[t.key] ?? {}} primary={exp.primary_metric} />
        </Panel>
      ))}

      <Panel title="How to read this">
        <div className="flex items-start gap-3 text-xs">
          <Info className="mt-0.5 size-4 shrink-0 text-muted" aria-hidden />
          <ul className="space-y-1.5 text-text">
            <li>
              <span className="font-medium">Rate with 95% CI.</span> The dot is the observed rate; the whisker is the Wilson interval where
              the true rate plausibly lies. Overlapping whiskers are a hint, not a test.
            </li>
            <li>
              <span className="font-medium">Absolute lift</span> is treatment minus control in percentage points, with a Newcombe 95%
              interval. If that interval includes zero, the difference could be chance.
            </li>
            <li>
              <span className="font-medium">p-value</span> comes from a two-proportion z-test. Below 0.05 we reject H0.
            </li>
            <li>
              <span className="font-medium">Only the primary metric decides the verdict.</span> Secondary metrics are descriptive; testing
              several at once without correction would inflate false positives.
            </li>
            <li>
              <span className="font-medium">Why no winner below the minimum sample?</span> Peeking at small samples and stopping when a
              number looks good is the most common way A/B tests lie. The minimum is fixed before launch; until every arm reaches it (and
              has at least 5 events each way), the verdict stays &ldquo;insufficient&rdquo; however large the observed lift.
            </li>
          </ul>
        </div>
      </Panel>
    </div>
  );
}
