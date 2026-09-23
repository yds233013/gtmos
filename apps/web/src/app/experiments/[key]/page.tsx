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
import { Badge, DemoBadge } from "@/components/ui/badge";
import { PageHeader } from "@/components/ui/page-header";
import { Panel } from "@/components/ui/panel";
import { ScoreBar } from "@/components/ui/score-bar";
import { ErrorState } from "@/components/ui/states";
import { Table, Td, Th, THead, Tr } from "@/components/ui/table";
import { api, ApiError } from "@/lib/api";
import { date, money, num, pct } from "@/lib/format";
import { cn } from "@/lib/utils";

import { actionMeta, CeilingBar, GuardrailBadge } from "../guardrail-ui";
import type { GuardedComparison, GuardedExperiment, GuardedVariant, GuardrailCheck } from "../types";

const METRIC_ORDER = ["reply", "positive_reply", "meeting", "opportunity"];
const GUARDRAIL_ORDER = ["bounce", "unsubscribe", "spam_complaint", "negative_reply"];

/** Deduped per request so generateMetadata and the page share one API call. */
const fetchExperiment = cache((key: string) => api<GuardedExperiment>(`/experiments/${encodeURIComponent(key)}`));

async function load(key: string): Promise<{ exp: GuardedExperiment | null; error: string | null }> {
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

function GuardrailTable({ checks }: { checks: GuardrailCheck[] }) {
  return (
    <Table>
      <THead>
        <tr>
          <Th>Guardrail</Th>
          <Th align="right">Control</Th>
          <Th align="right">Treatment</Th>
          <Th align="right">Ceiling</Th>
          <Th className="min-w-28">Treatment vs ceiling</Th>
          <Th>Status</Th>
        </tr>
      </THead>
      <tbody>
        {checks.map((g) => (
          <Tr key={g.metric} className={cn(g.status === "breach" && "bg-danger-soft/40")}>
            <Td className="align-top">
              <div className="font-medium whitespace-nowrap">{g.label}</div>
              <p className="mt-0.5 max-w-80 text-[11px] leading-snug text-muted">{g.rationale}</p>
            </Td>
            <Td align="right" className="align-top tabular whitespace-nowrap">
              {pct(g.control.rate, 2)}
              <div className="text-[11px] text-muted">
                {num(g.control.successes)} / {num(g.control.n)}
              </div>
            </Td>
            <Td align="right" className="align-top tabular whitespace-nowrap">
              <span className={cn(g.status === "breach" && "font-semibold text-danger")}>{pct(g.treatment.rate, 2)}</span>
              <div className="text-[11px] text-muted">
                {num(g.treatment.successes)} / {num(g.treatment.n)}
              </div>
            </Td>
            <Td align="right" className="align-top tabular whitespace-nowrap text-muted">
              {pct(g.ceiling, 2)}
            </Td>
            <Td className="align-top">
              <div className="py-1">
                <CeilingBar check={g} />
              </div>
            </Td>
            <Td className="max-w-72 align-top">
              <GuardrailBadge status={g.status} />
              <p className="mt-1 text-[11px] leading-snug text-muted">{g.reason}</p>
            </Td>
          </Tr>
        ))}
      </tbody>
    </Table>
  );
}

function ComparisonTable({
  control,
  treatment,
  comps,
  primary,
}: {
  control: GuardedVariant;
  treatment: GuardedVariant;
  comps: Record<string, GuardedComparison>;
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
                {cmp?.mde_abs != null ? (
                  <div
                    className="mt-0.5 text-[11px] text-muted"
                    title="Minimum detectable effect: the smallest lift this sample size would catch 80% of the time at 95% confidence"
                  >
                    MDE {pp(cmp.mde_abs)} · acts above {pp(cmp.practical_threshold)}
                  </div>
                ) : cmp?.required_n_per_variant ? (
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
                    {isPrimary && <p className="mt-1 text-[11px] leading-snug text-muted">{cmp.practical_note}</p>}
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
  const insufficient = exp.verdict === "insufficient_sample" || exp.verdict === "insufficient_events";
  const smallest = Math.min(...exp.variants.map((v) => v.units));
  const rec = exp.recommendation;
  const action = actionMeta(rec?.action);
  const ActionIcon = action.icon;
  const primaryCmp = exp.comparisons[treatments[0]?.key ?? ""]?.[exp.primary_metric];

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

      <section className={cn("rounded-lg border p-4", action.box)} aria-labelledby="verdict-heading">
        <div className="flex items-start gap-3">
          <ActionIcon className={cn("mt-0.5 size-5 shrink-0", action.ink)} aria-hidden />
          <div className="min-w-0 flex-1">
            <h2 id="verdict-heading" className={cn("text-base font-semibold", action.ink)}>
              {rec?.headline ?? verdict.label}
            </h2>
            <p className="mt-1 text-sm text-text">{rec?.reasoning ?? exp.verdict_explanation}</p>
            <div className="mt-2 flex flex-wrap items-center gap-2 text-[11px] text-muted">
              <span className="inline-flex items-center gap-1">
                Statistical verdict on {metricLabel(exp.primary_metric).toLowerCase()}: <VerdictBadge verdict={exp.verdict} />
              </span>
              {primaryCmp?.mde_abs != null && <span>Detectable at this sample: {pp(primaryCmp.mde_abs)} or more</span>}
              {primaryCmp && <span>Acts above {pp(primaryCmp.practical_threshold)}</span>}
              {rec?.blocking_guardrails.map((m) => (
                <Badge key={m} tone="danger">
                  {metricLabel(m)} breached
                </Badge>
              ))}
            </div>
            {insufficient && !rec?.blocking_guardrails.length && (
              <p className="mt-2 text-xs text-muted">
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

      {treatments.map((t) => {
        const checks = GUARDRAIL_ORDER.map((m) => exp.guardrails[t.key]?.[m]).filter((g): g is GuardrailCheck => Boolean(g));
        if (!checks.length) return null;
        const breached = checks.filter((g) => g.status === "breach").length;
        return (
          <Panel
            key={`guardrails-${t.key}`}
            title={`Guardrails · ${t.name}`}
            description="Checked for harm, not for lift. A guardrail past its ceiling blocks the ship decision whatever the primary metric did."
            bodyClassName="p-0"
            actions={breached ? <Badge tone="danger">{breached} breached</Badge> : <Badge tone="success">All within limits</Badge>}
          >
            <GuardrailTable checks={checks} />
            <p className="border-t border-border px-4 py-3 text-[11px] leading-snug text-muted">
              This is why reply rate alone is a bad objective. A subject line that implies a problem the reader has to open the email to
              resolve reliably earns replies — and unsubscribes, spam complaints and &ldquo;take us off your list&rdquo; from everyone it
              annoyed. The reply lands this quarter; the burnt domain lands next one, on someone else&rsquo;s campaign.
            </p>
          </Panel>
        );
      })}

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
              <span className="font-medium">Guardrails are limits, not metrics.</span> They are never traded off against the primary metric
              and never counted as a win when they improve. Each one is checked one-sided against a ceiling set before launch, and a
              confirmed breach turns the recommendation to &ldquo;do not ship&rdquo; even when the treatment won.
            </li>
            <li>
              <span className="font-medium">MDE</span> is the smallest lift this sample size would have caught 80% of the time. When a test
              comes back null, compare it to the MDE: a null with a 10 pp MDE means the test was blind, not that nothing happened.
            </li>
            <li>
              <span className="font-medium">Significant is not the same as worth shipping.</span> Below the practical threshold shown on the
              primary row, the lift costs more in rewriting sequences and retraining reps than it returns, so the call is &ldquo;no
              change&rdquo; even at p &lt; 0.05.
            </li>
            <li>
              <span className="font-medium">What randomisation buys.</span> A causal read of the gap between these two arms, on this
              audience, in this window. Not a claim about other segments, other quarters or other channels.
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
