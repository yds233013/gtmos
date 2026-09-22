import { cn } from "@/lib/utils";
import type { Grade, HealthStatus } from "@/lib/types";

type Tone = "neutral" | "accent" | "success" | "warning" | "danger" | "info";

const TONES: Record<Tone, string> = {
  neutral: "bg-panel-2 text-muted border-border",
  accent: "bg-accent-soft text-accent-text border-transparent",
  success: "bg-success-soft text-success border-transparent",
  warning: "bg-warning-soft text-warning border-transparent",
  danger: "bg-danger-soft text-danger border-transparent",
  info: "bg-info-soft text-info border-transparent",
};

export function Badge({
  tone = "neutral",
  children,
  className,
  title,
}: {
  tone?: Tone;
  children: React.ReactNode;
  className?: string;
  title?: string;
}) {
  return (
    <span
      title={title}
      className={cn(
        "inline-flex items-center gap-1 whitespace-nowrap rounded border px-1.5 py-0.5 text-[11px] font-medium leading-4",
        TONES[tone],
        className,
      )}
    >
      {children}
    </span>
  );
}

const GRADE_TONE: Record<Grade, Tone> = { A: "success", B: "info", C: "warning", D: "neutral", X: "danger" };

export function GradeBadge({ grade, score }: { grade: Grade | null | undefined; score?: number | null }) {
  if (!grade) return <Badge>Unscored</Badge>;
  return (
    <Badge tone={GRADE_TONE[grade]} title={grade === "X" ? "Excluded by ICP rules" : `Grade ${grade}`}>
      <span className="font-semibold">{grade}</span>
      {score !== undefined && score !== null && <span className="tabular opacity-80">{score}</span>}
    </Badge>
  );
}

/** Marks synthetic data everywhere it appears. */
export function DemoBadge({ label = "DEMO" }: { label?: string }) {
  return (
    <Badge tone="warning" title="Synthetic demo data generated deterministically by the GTMOS seed">
      {label}
    </Badge>
  );
}

export function SimulatedBadge() {
  return (
    <Badge tone="warning" title="Performed by a simulated adapter; no external system was called">
      SIMULATED
    </Badge>
  );
}

export function LiveBadge() {
  return <Badge tone="success">LIVE</Badge>;
}

const STATUS_TONE: Record<string, Tone> = {
  healthy: "success",
  succeeded: "success",
  processed: "success",
  approved: "success",
  ready: "success",
  won: "success",
  closed_won: "success",
  assigned: "success",
  valid: "success",
  warning: "warning",
  partial: "warning",
  review: "accent",
  running: "info",
  queued: "info",
  retrying: "warning",
  pending: "neutral",
  skipped: "neutral",
  draft: "neutral",
  kept_owner: "info",
  degraded: "warning",
  unmatched: "warning",
  risky: "warning",
  critical: "danger",
  failed: "danger",
  dead_letter: "danger",
  rejected: "danger",
  lost: "danger",
  closed_lost: "danger",
  invalid: "danger",
  high: "danger",
  medium: "warning",
  low: "neutral",
};

export function StatusBadge({ status, label }: { status: string | HealthStatus; label?: string }) {
  return <Badge tone={STATUS_TONE[status] ?? "neutral"}>{label ?? status.replace(/_/g, " ")}</Badge>;
}

export function StatusDot({ status }: { status: string }) {
  const color =
    STATUS_TONE[status] === "success"
      ? "bg-success"
      : STATUS_TONE[status] === "warning"
        ? "bg-warning"
        : STATUS_TONE[status] === "danger"
          ? "bg-danger"
          : "bg-subtle";
  return <span aria-hidden className={cn("inline-block size-2 shrink-0 rounded-full", color)} />;
}
