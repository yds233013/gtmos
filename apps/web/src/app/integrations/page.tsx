import Link from "next/link";

import { IntegrationCard, PostureLegend } from "@/components/integrations/integration-card";
import { PageHeader } from "@/components/ui/page-header";
import { Panel } from "@/components/ui/panel";
import { StatCell, StatGrid } from "@/components/ui/stat";
import { EmptyState, ErrorState } from "@/components/ui/states";
import { api, settle } from "@/lib/api";
import { num } from "@/lib/format";
import type { IntegrationStatusResponse } from "@/lib/types";

export const metadata = { title: "Integrations" };

export default async function IntegrationsPage() {
  const [status] = await settle(api<IntegrationStatusResponse>("/integrations/status?days=7"));

  if (!status) {
    return (
      <div className="space-y-6">
        <PageHeader title="Integrations" />
        <ErrorState
          title="Couldn't load integration status"
          message="The GTMOS API did not respond. Start the backend and reload."
        />
      </div>
    );
  }

  const items = status.integrations;
  const verified = items.filter((i) => i.verification === "verified_by_execution").length;
  const local = items.filter((i) => i.verification === "verified_locally").length;
  const simulated = items.filter((i) => i.verification === "simulated" || i.verification === "unverified").length;
  const reached = items.filter((i) => i.reached_real_service).length;
  const errors = items.reduce((a, i) => a + i.window.error_count, 0);

  return (
    <div className="space-y-6">
      <PageHeader
        title="Integrations"
        eyebrow={`Boundaries · health and verification · last ${status.window_days} days`}
        description="What GTMOS is actually connected to, and how much of each connection has genuinely run. One tool executes against a real instance, one runs on a simulated adapter, and two are contracts that work locally but have never met the real service. Every number here is derived from stored deliveries, sync runs and enrichment attempts."
      />

      <StatGrid>
        {/* Six columns is a tight measure — each `sub` is kept short enough to survive the
            truncation rather than trailing off mid-word. The long form is the `hint`. */}
        <StatCell
          label="Boundaries"
          value={num(items.length)}
          sub="Tools in the stack"
          hint="HubSpot, n8n, PostHog and Clay"
        />
        <StatCell
          label="Verified by execution"
          value={num(verified)}
          sub="Ran for real"
          hint="Requests were genuinely exchanged with a real running instance of the tool"
        />
        <StatCell
          label="Verified locally"
          value={num(local)}
          sub="Contract only"
          hint="The documented payload shape was exercised against GTMOS's own endpoint. No account exists."
        />
        <StatCell
          label="Simulated or unrun"
          value={num(simulated)}
          sub="Live adapter unrun"
          hint="Exercised through the simulated adapter. The live adapter has never executed."
        />
        <StatCell
          label="Real services reached"
          value={`${num(reached)} of ${num(items.length)}`}
          sub="The rest, never"
          hint="Every other boundary has never talked to the vendor"
        />
        <StatCell
          label={`Errors · ${status.window_days}d`}
          value={<span className={errors > 0 ? "text-warning" : undefined}>{num(errors)}</span>}
          sub="Deliveries and syncs"
          hint="Failed inbound deliveries and failed sync runs, combined"
        />
      </StatGrid>

      <Panel
        title="How to read these labels"
        description="Two independent axes: what the configuration does, and how much of it has ever happened"
      >
        <PostureLegend modes={status.modes} levels={status.verification_levels} />
        <p className="mt-4 border-t border-border pt-3 text-[11px] text-muted">
          A boundary is only green when requests have genuinely been exchanged with a real running instance of the
          tool. Nothing is labelled &ldquo;Connected&rdquo;, because three of these four have never been.
        </p>
      </Panel>

      {items.length ? (
        <ul className="grid gap-4 xl:grid-cols-2">
          {items.map((i) => (
            <IntegrationCard key={i.provider} i={i} />
          ))}
        </ul>
      ) : (
        <EmptyState title="No integration boundaries registered" />
      )}

      <Panel title="Elsewhere" description="Related surfaces">
        <ul className="space-y-1 text-xs">
          <li>
            <Link href="/operations" className="text-accent-text hover:underline">
              Operations
            </Link>
            <span className="text-muted"> — cross-cutting health: workflow runs, every webhook source, enrichment providers, routing latency.</span>
          </li>
          <li>
            <Link href="/settings?tab=integrations" className="text-accent-text hover:underline">
              Settings · Integrations
            </Link>
            <span className="text-muted"> — the full provider registry, including the simulated enrichment providers and the LLM. Secrets are read from the API&apos;s environment and never displayed.</span>
          </li>
          <li>
            <Link href="/stack-inspector" className="text-accent-text hover:underline">
              Stack Inspector
            </Link>
            <span className="text-muted"> — whether the data these boundaries carry is actually being used well.</span>
          </li>
        </ul>
      </Panel>
    </div>
  );
}
