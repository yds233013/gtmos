import { ArrowRight } from "lucide-react";
import Link from "next/link";

import { duration } from "@/components/systems/format";
import { Badge } from "@/components/ui/badge";
import { num, relTime, titleCase } from "@/lib/format";
import type { IntegrationStatus } from "@/lib/types";
import { cn } from "@/lib/utils";

import { HealthPill, ModeBadge, RealServiceBadge, VerificationBadge } from "./labels";

const DIRECTION_LABEL: Record<string, string> = {
  inbound: "Inbound only",
  outbound: "Outbound only",
  bidirectional: "Both directions",
};

function Metric({ label, value, tone }: { label: string; value: React.ReactNode; tone?: "danger" }) {
  return (
    <div className="min-w-0">
      <dt className="truncate text-[11px] text-muted">{label}</dt>
      <dd className={cn("tabular mt-0.5 truncate text-sm font-medium text-text", tone === "danger" && "text-danger")}>
        {value}
      </dd>
    </div>
  );
}

/** A failure older than the health window did not feed the pill above it. Say so, rather than
 *  leaving a green "Healthy" sitting on top of a red error strip with no explanation. */
function outsideWindow(at: string | null, days: number): boolean {
  if (!at) return false;
  return Date.now() - new Date(at).getTime() > days * 86_400_000;
}

export function IntegrationCard({ i }: { i: IntegrationStatus }) {
  const w = i.window;
  const latency = w.latency.inbound_p50_ms ?? w.latency.sync_p50_ms;
  const latencyLabel = w.latency.inbound_p50_ms !== null ? "Inbound p50" : "Sync p50";
  const staleFailure = outsideWindow(i.last_failure_at, w.days);
  return (
    <li className="flex flex-col rounded-lg border border-border bg-panel">
      <header className="flex flex-col gap-2 border-b border-border px-4 py-3">
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <h3 className="truncate text-sm font-semibold text-text">{i.display_name}</h3>
            <p className="truncate text-[11px] text-muted">
              {titleCase(i.category)} · {DIRECTION_LABEL[i.direction] ?? titleCase(i.direction)}
            </p>
          </div>
          <HealthPill health={i.health} />
        </div>
        <div className="flex flex-wrap items-center gap-1.5">
          <VerificationBadge level={i.verification} title={i.verification_description} />
          <ModeBadge mode={i.mode} title={i.mode_description} />
          <RealServiceBadge reached={i.reached_real_service} />
        </div>
      </header>

      <div className="flex flex-1 flex-col gap-3 px-4 py-3">
        <p className="text-xs text-muted">{i.summary}</p>

        <div>
          <h4 className="text-[11px] font-semibold uppercase tracking-wide text-subtle">What moves</h4>
          <ul className="mt-1 space-y-1">
            {i.moves.map((m) => (
              <li key={m} className="text-[11px] leading-snug text-text">
                {m}
              </li>
            ))}
          </ul>
        </div>

        <dl className="grid grid-cols-2 gap-x-3 gap-y-2 border-t border-border pt-3">
          <Metric label="Last inbound event" value={relTime(i.last_inbound_event_at)} />
          <Metric label="Last success" value={relTime(i.last_success_at)} />
          <Metric
            label={`Errors · ${w.days}d`}
            value={`${num(w.error_count)}${w.retry_count ? ` · ${num(w.retry_count)} retries` : ""}`}
            tone={w.error_count > 0 ? "danger" : undefined}
          />
          <Metric label={`Records · ${w.days}d`} value={num(w.records_processed)} />
          <Metric label={latencyLabel} value={duration(latency)} />
          <Metric
            label="Real deliveries (all time)"
            value={`${num(i.lifetime.real_deliveries)}${
              i.lifetime.synthetic_history ? ` · ${num(i.lifetime.synthetic_history)} seeded` : ""
            }`}
          />
        </dl>

        {i.last_failure && (
          <p
            className={cn(
              "break-words rounded px-2 py-1 text-[11px]",
              staleFailure ? "bg-panel-2 text-muted" : "bg-danger-soft text-danger",
            )}
          >
            Last failure {relTime(i.last_failure_at)}: {i.last_failure}
            {staleFailure && <span> — older than the {w.days}-day window, so it does not affect health.</span>}
          </p>
        )}
      </div>

      <div className="space-y-2 border-t border-border bg-panel-2/50 px-4 py-3 text-[11px]">
        {i.blocking.length ? (
          <>
            <p className="font-medium text-text">Still required to make this live</p>
            <ul className="space-y-0.5">
              {i.blocking.map((b) => (
                <li key={b} className="break-words text-muted">
                  · {b}
                </li>
              ))}
            </ul>
          </>
        ) : (
          <p className="text-success">Everything this boundary needs is configured.</p>
        )}
        <p className="break-words text-muted">{i.verification_note}</p>
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1 pt-1">
          {i.docs.map((d) => (
            <span key={d.path} className="inline-flex items-center gap-1">
              <span className="text-muted">{d.label}</span>
              <code className="break-all font-mono text-[11px] text-subtle">{d.path}</code>
            </span>
          ))}
        </div>
        <Link
          href={`/integrations/${i.provider}`}
          className="inline-flex items-center gap-1 font-medium text-accent-text hover:underline"
        >
          Inspect deliveries, syncs and errors
          <ArrowRight className="size-3" aria-hidden />
        </Link>
      </div>
    </li>
  );
}

/** The legend that makes the labels readable without hovering anything. */
export function PostureLegend({
  modes,
  levels,
}: {
  modes: Record<string, string>;
  levels: Record<string, string>;
}) {
  return (
    <div className="grid gap-4 md:grid-cols-2">
      <div>
        <h3 className="text-[11px] font-semibold uppercase tracking-wide text-subtle">
          Verification — how much has actually happened
        </h3>
        <dl className="mt-2 space-y-1.5">
          {(["verified_by_execution", "verified_locally", "simulated", "unverified"] as const).map((k) => (
            <div key={k} className="flex flex-col gap-1 sm:flex-row sm:items-start sm:gap-2">
              <dt className="shrink-0">
                <VerificationBadge level={k} />
              </dt>
              <dd className="min-w-0 text-[11px] text-muted">{levels[k]}</dd>
            </div>
          ))}
        </dl>
      </div>
      <div>
        <h3 className="text-[11px] font-semibold uppercase tracking-wide text-subtle">
          Mode — what the running configuration does
        </h3>
        <dl className="mt-2 space-y-1.5">
          {(["live", "test", "demo", "not_configured"] as const).map((k) => (
            <div key={k} className="flex flex-col gap-1 sm:flex-row sm:items-start sm:gap-2">
              <dt className="shrink-0">
                <Badge tone={k === "live" ? "success" : k === "test" ? "info" : k === "demo" ? "warning" : "neutral"}>
                  {k === "not_configured" ? "Not configured" : titleCase(k)}
                </Badge>
              </dt>
              <dd className="min-w-0 text-[11px] text-muted">{modes[k]}</dd>
            </div>
          ))}
        </dl>
      </div>
    </div>
  );
}
