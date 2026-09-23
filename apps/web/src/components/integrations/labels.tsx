import { Badge, StatusDot } from "@/components/ui/badge";
import type { IntegrationHealth, IntegrationMode, VerificationLevel } from "@/lib/types";

/**
 * The honesty layer.
 *
 * Four green "Connected" badges would be a lie: GTMOS talks to four tools at four different levels of
 * proof. The headline label is driven by the *verification* level, not by whether a row exists, so a
 * boundary that has never spoken to the real service can never render as green.
 */

type Tone = "neutral" | "accent" | "success" | "warning" | "danger" | "info";

export const VERIFICATION_LABEL: Record<VerificationLevel, { label: string; tone: Tone; short: string }> = {
  verified_by_execution: { label: "Live — verified by execution", tone: "success", short: "Verified by execution" },
  verified_locally: { label: "Local (verified)", tone: "info", short: "Verified locally" },
  simulated: { label: "Demo adapter", tone: "warning", short: "Simulated only" },
  unverified: { label: "Ready — needs credentials", tone: "neutral", short: "Never run" },
};

export const MODE_LABEL: Record<IntegrationMode, { label: string; tone: Tone }> = {
  live: { label: "Live", tone: "success" },
  test: { label: "Test", tone: "info" },
  demo: { label: "Demo", tone: "warning" },
  not_configured: { label: "Not configured", tone: "neutral" },
};

const HEALTH_LABEL: Record<IntegrationHealth, string> = {
  healthy: "Healthy",
  degraded: "Degraded",
  failing: "Failing",
  idle: "Idle",
  not_configured: "Not configured",
};

const HEALTH_DOT: Record<IntegrationHealth, string> = {
  healthy: "healthy",
  degraded: "degraded",
  failing: "failed",
  idle: "pending",
  not_configured: "pending",
};

/** The headline claim: how much of this boundary has ever actually happened. */
export function VerificationBadge({ level, title }: { level: VerificationLevel; title?: string }) {
  const v = VERIFICATION_LABEL[level];
  return (
    <Badge tone={v.tone} title={title}>
      {v.label}
    </Badge>
  );
}

/** What the running configuration does right now. */
export function ModeBadge({ mode, title }: { mode: IntegrationMode; title?: string }) {
  const m = MODE_LABEL[mode];
  return (
    <Badge tone={m.tone} title={title}>
      Mode: {m.label}
    </Badge>
  );
}

export function HealthPill({ health }: { health: IntegrationHealth }) {
  return (
    <span className="inline-flex items-center gap-1.5 text-[11px] text-muted">
      <StatusDot status={HEALTH_DOT[health]} />
      {HEALTH_LABEL[health]}
    </span>
  );
}

/**
 * States in one word whether anything has ever been exchanged with the real third-party service.
 * Rendered on every card so the distinction survives a three-second glance.
 */
export function RealServiceBadge({ reached }: { reached: boolean }) {
  return reached ? (
    <Badge tone="success" title="Requests have genuinely been exchanged with a real running instance of this tool">
      Real service reached
    </Badge>
  ) : (
    <Badge tone="neutral" title="Nothing has ever been sent to, or received from, the real third-party service">
      Real service never reached
    </Badge>
  );
}
