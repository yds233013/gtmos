import { CircleCheck, CircleMinus, Hourglass, type LucideIcon } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { pct } from "@/lib/format";
import { cn } from "@/lib/utils";

type Tone = "neutral" | "success" | "warning" | "info";

interface VerdictMeta {
  label: string;
  tone: Tone;
  icon: LucideIcon;
  box: string;
  ink: string;
}

/** Only a significant treatment win is green. "Insufficient" is a warning, never a result. */
const VERDICTS: Record<string, VerdictMeta> = {
  treatment_better: {
    label: "Treatment wins",
    tone: "success",
    icon: CircleCheck,
    box: "border-success/30 bg-success-soft",
    ink: "text-success",
  },
  control_better: {
    label: "Control wins",
    tone: "info",
    icon: CircleCheck,
    box: "border-info/30 bg-info-soft",
    ink: "text-info",
  },
  no_significant_difference: {
    label: "No significant difference",
    tone: "neutral",
    icon: CircleMinus,
    box: "border-border bg-panel-2",
    ink: "text-text",
  },
  insufficient_sample: {
    label: "Insufficient sample",
    tone: "warning",
    icon: Hourglass,
    box: "border-warning/30 bg-warning-soft",
    ink: "text-warning",
  },
  insufficient_events: {
    label: "Insufficient events",
    tone: "warning",
    icon: Hourglass,
    box: "border-warning/30 bg-warning-soft",
    ink: "text-warning",
  },
};

const FALLBACK: VerdictMeta = { label: "No verdict", tone: "neutral", icon: CircleMinus, box: "border-border bg-panel-2", ink: "text-text" };

export function verdictMeta(verdict: string | null | undefined): VerdictMeta {
  return (verdict && VERDICTS[verdict]) || { ...FALLBACK, label: verdict ? verdict.replace(/_/g, " ") : FALLBACK.label };
}

export function VerdictBadge({ verdict }: { verdict: string | null | undefined }) {
  const m = verdictMeta(verdict);
  return <Badge tone={m.tone}>{m.label}</Badge>;
}

export const METRIC_LABEL: Record<string, string> = {
  reply: "Reply rate",
  positive_reply: "Positive reply rate",
  meeting: "Meeting rate",
  opportunity: "Opportunity rate",
};

export function metricLabel(key: string): string {
  return METRIC_LABEL[key] ?? key.replace(/_/g, " ");
}

/** Percentage points with sign, e.g. +8.7 pp. */
export function pp(value: number | null | undefined, digits = 1): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  const v = value * 100;
  return `${v > 0 ? "+" : v < 0 ? "−" : ""}${Math.abs(v).toFixed(digits)} pp`;
}

export function signedPct(value: number | null | undefined, digits = 0): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  return `${value > 0 ? "+" : value < 0 ? "−" : ""}${pct(Math.abs(value), digits)}`;
}

export function pValue(p: number | null | undefined): string {
  if (p === null || p === undefined || Number.isNaN(p)) return "—";
  return p < 0.001 ? "< 0.001" : p.toFixed(3);
}

/** Round a max rate up to a readable axis end (e.g. 0.43 → 0.5). */
export function niceMax(value: number): number {
  const steps = [0.05, 0.1, 0.15, 0.2, 0.25, 0.3, 0.4, 0.5, 0.6, 0.8, 1];
  return steps.find((s) => s >= value) ?? 1;
}

/**
 * One interval on a shared 0..max scale: whisker from ci_low to ci_high with a point at the rate.
 * Plain HTML so it scales with the column and stays crisp.
 */
export function IntervalBar({
  low,
  high,
  point,
  max,
  variant,
  label,
}: {
  low: number;
  high: number;
  point: number;
  max: number;
  variant: "control" | "treatment";
  label: string;
}) {
  const pos = (v: number) => `${Math.max(0, Math.min(1, v / max)) * 100}%`;
  const color = variant === "control" ? "bg-muted" : "bg-accent";
  return (
    <div className="relative h-3 w-full" role="img" aria-label={`${label}: ${pct(point)} (95% CI ${pct(low)} to ${pct(high)})`}>
      <div className="absolute inset-x-0 top-1/2 h-px -translate-y-1/2 bg-border" aria-hidden />
      <div className={cn("absolute top-1/2 h-0.5 -translate-y-1/2 rounded", color)} style={{ left: pos(low), width: `calc(${pos(high)} - ${pos(low)})` }} />
      <div className={cn("absolute top-0.5 h-2 w-px", color)} style={{ left: pos(low) }} />
      <div className={cn("absolute top-0.5 h-2 w-px", color)} style={{ left: pos(high) }} />
      <div
        className={cn("absolute top-1/2 size-2 -translate-x-1/2 -translate-y-1/2 rounded-full ring-2 ring-panel", color)}
        style={{ left: pos(point) }}
      />
    </div>
  );
}

export function IntervalAxis({ max }: { max: number }) {
  const ticks = [0, max / 2, max];
  return (
    <div className="relative h-3 w-full text-[10px] text-subtle" aria-hidden>
      {ticks.map((t, i) => (
        <span
          key={t}
          className={cn("tabular absolute top-0", i === 0 ? "left-0" : i === ticks.length - 1 ? "right-0" : "-translate-x-1/2")}
          style={i === 1 ? { left: "50%" } : undefined}
        >
          {pct(t, 0)}
        </span>
      ))}
    </div>
  );
}
