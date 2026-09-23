import { CircleCheck, CircleMinus, CircleSlash, Hourglass, type LucideIcon, ShieldAlert, ShieldCheck, TriangleAlert } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { pct } from "@/lib/format";
import { cn } from "@/lib/utils";

import type { GuardrailCheck, GuardrailStatus, RecommendationAction } from "./types";

type Tone = "neutral" | "accent" | "success" | "warning" | "danger" | "info";

interface Meta {
  label: string;
  tone: Tone;
  icon: LucideIcon;
  box: string;
  ink: string;
}

/** Only a breach is red, and only a clean ship is green. Everything else reads as "not yet". */
const ACTIONS: Record<RecommendationAction, Meta> = {
  ship: { label: "Ship the treatment", tone: "success", icon: CircleCheck, box: "border-success/30 bg-success-soft", ink: "text-success" },
  do_not_ship: { label: "Do not ship", tone: "danger", icon: ShieldAlert, box: "border-danger/30 bg-danger-soft", ink: "text-danger" },
  keep_running: { label: "Keep running", tone: "warning", icon: Hourglass, box: "border-warning/30 bg-warning-soft", ink: "text-warning" },
  no_change: { label: "No change", tone: "neutral", icon: CircleMinus, box: "border-border bg-panel-2", ink: "text-text" },
};

const FALLBACK: Meta = { label: "No recommendation", tone: "neutral", icon: CircleMinus, box: "border-border bg-panel-2", ink: "text-text" };

export function actionMeta(action: RecommendationAction | null | undefined): Meta {
  return (action && ACTIONS[action]) || FALLBACK;
}

const GUARDRAIL_STATUS: Record<GuardrailStatus, { label: string; tone: Tone; icon: LucideIcon }> = {
  ok: { label: "Within limit", tone: "success", icon: ShieldCheck },
  watch: { label: "Watch", tone: "warning", icon: TriangleAlert },
  breach: { label: "Breached", tone: "danger", icon: ShieldAlert },
  no_data: { label: "No data", tone: "neutral", icon: CircleSlash },
};

export function GuardrailBadge({ status }: { status: GuardrailStatus }) {
  const m = GUARDRAIL_STATUS[status] ?? GUARDRAIL_STATUS.no_data;
  const Icon = m.icon;
  return (
    <Badge tone={m.tone}>
      <Icon className="size-3" aria-hidden />
      {m.label}
    </Badge>
  );
}

export function ActionBadge({ action }: { action: RecommendationAction | null | undefined }) {
  const m = actionMeta(action);
  return <Badge tone={m.tone}>{m.label}</Badge>;
}

/**
 * A guardrail on its own scale: the ceiling is the only landmark that matters, so the bar is drawn
 * against it rather than against the other arm. Anything past the ceiling overflows into the danger zone.
 */
export function CeilingBar({ check }: { check: GuardrailCheck }) {
  const max = Math.max(check.ceiling * 2, check.treatment.ci_high, check.control.rate, 1e-6);
  const at = (v: number) => `${Math.max(0, Math.min(1, v / max)) * 100}%`;
  const tone = check.status === "breach" ? "bg-danger" : check.status === "watch" ? "bg-warning" : "bg-success";
  return (
    <div
      className="relative h-4 w-full min-w-24"
      role="img"
      aria-label={`${check.label}: treatment ${pct(check.treatment.rate, 2)} (95% CI ${pct(check.treatment.ci_low, 2)} to ${pct(check.treatment.ci_high, 2)}), control ${pct(check.control.rate, 2)}, ceiling ${pct(check.ceiling, 2)}`}
    >
      <div className="absolute inset-x-0 top-1/2 h-px -translate-y-1/2 bg-border" aria-hidden />
      <div
        className={cn("absolute top-1/2 h-0.5 -translate-y-1/2 rounded", tone)}
        style={{ left: at(check.treatment.ci_low), width: `calc(${at(check.treatment.ci_high)} - ${at(check.treatment.ci_low)})` }}
        aria-hidden
      />
      <div
        className={cn("absolute top-1/2 size-2 -translate-x-1/2 -translate-y-1/2 rounded-full ring-2 ring-panel", tone)}
        style={{ left: at(check.treatment.rate) }}
        aria-hidden
      />
      <div
        className="absolute top-1/2 size-1.5 -translate-x-1/2 -translate-y-1/2 rounded-full bg-muted ring-2 ring-panel"
        style={{ left: at(check.control.rate) }}
        aria-hidden
      />
      <div className="absolute inset-y-0 w-px bg-danger" style={{ left: at(check.ceiling) }} aria-hidden />
    </div>
  );
}
