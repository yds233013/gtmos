import { Badge, LiveBadge, StatusBadge } from "@/components/ui/badge";
import { EmptyState } from "@/components/ui/states";
import type { Integration } from "@/components/insights/types";
import { relTime, titleCase } from "@/lib/format";
import type { Workspace } from "@/lib/types";

const CATEGORY_ORDER = ["crm", "enrichment", "llm", "product_analytics", "workflow_automation"];
const CATEGORY_LABEL: Record<string, string> = {
  crm: "CRM",
  enrichment: "Enrichment",
  llm: "LLM",
  product_analytics: "Product analytics",
  workflow_automation: "Workflow automation",
};

/** What it takes to take each provider out of demo mode. */
const GO_LIVE: Record<string, { env: string[]; note: string }> = {
  hubspot: {
    env: ["HUBSPOT_ACCESS_TOKEN", "HUBSPOT_LIVE_WRITES_ENABLED=true"],
    note: "Private-app token with companies/contacts/deals write scopes. Writes stay simulated until the flag is also set; live writes then require the admin token.",
  },
  anthropic: {
    env: ["ANTHROPIC_API_KEY", "LLM_ENABLED=true"],
    note: "Research and drafts fall back to the deterministic template writer when either is missing.",
  },
  apollo: {
    env: ["APOLLO_API_KEY"],
    note: "Adds Apollo as a real provider at the front of the enrichment waterfall.",
  },
  posthog: {
    env: ["WEBHOOK_SECRET"],
    note: "Signs inbound product-event webhooks (HMAC). Point PostHog at the endpoint shown above.",
  },
  n8n: {
    env: ["WEBHOOK_SECRET"],
    note: "Signs inbound n8n webhooks (HMAC). Import the listed templates into n8n.",
  },
};

function ModeBadge({ mode }: { mode: string }) {
  if (mode === "live") return <LiveBadge />;
  if (mode === "demo")
    return (
      <Badge tone="warning" title="Runs against a simulated adapter">
        DEMO
      </Badge>
    );
  return <Badge tone="neutral">{mode === "disabled" ? "DISABLED" : mode.toUpperCase()}</Badge>;
}

/** Row modes are written at seed time; the workspace reports the mode the running API actually uses. */
function effectiveMode(i: Integration, ws: Workspace | null): string | null {
  if (!ws) return null;
  if (i.provider === "anthropic") return ws.llm_mode;
  if (i.provider === "hubspot") return ws.hubspot_mode;
  return null;
}

function ConfigList({ config }: { config: Record<string, unknown> }) {
  const entries = Object.entries(config);
  if (!entries.length) return null;
  return (
    <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-0.5 text-[11px]">
      {entries.map(([k, v]) => (
        <div key={k} className="contents">
          <dt className="text-muted">{titleCase(k)}</dt>
          <dd className="min-w-0 truncate font-mono text-text" title={String(v)}>
            {typeof v === "object" ? JSON.stringify(v) : String(v)}
          </dd>
        </div>
      ))}
    </dl>
  );
}

function IntegrationCard({ i, ws }: { i: Integration; ws: Workspace | null }) {
  const goLive = GO_LIVE[i.provider];
  const effective = effectiveMode(i, ws);
  const mode = effective ?? i.mode;
  const simulatedProvider = i.provider.startsWith("demo_");
  return (
    <li className="flex flex-col rounded-lg border border-border bg-panel">
      <div className="flex items-start justify-between gap-2 border-b border-border px-4 py-3">
        <div className="min-w-0">
          <h4 className="truncate text-sm font-medium text-text">{i.display_name}</h4>
          <p className="font-mono text-[11px] text-muted">{i.provider}</p>
        </div>
        <div className="flex shrink-0 items-center gap-1.5">
          <ModeBadge mode={mode} />
          <StatusBadge status={i.status === "not_configured" ? "skipped" : i.status} label={titleCase(i.status)} />
        </div>
      </div>
      <div className="flex-1 space-y-2.5 px-4 py-3 text-xs">
        {effective && effective !== i.mode && (
          <p className="text-[11px] text-warning">
            Registry says {i.mode.toUpperCase()}, but the running API is in {effective.toUpperCase()} mode.
          </p>
        )}
        <ConfigList config={i.config} />
        <div className="flex flex-wrap gap-x-4 gap-y-0.5 text-[11px] text-muted">
          <span>Last success {relTime(i.last_success_at)}</span>
          {i.last_error_at && <span className="text-danger">Last error {relTime(i.last_error_at)}</span>}
        </div>
        {i.last_error && <p className="rounded bg-danger-soft px-2 py-1 text-[11px] text-danger">{i.last_error}</p>}
      </div>
      <div className="border-t border-border bg-panel-2/50 px-4 py-2.5 text-[11px]">
        {mode === "live" ? (
          <p className="text-success">Live. Configured via {goLive?.env.join(" + ") ?? "environment"}.</p>
        ) : goLive ? (
          <>
            <p className="font-medium text-text">To go live, set</p>
            <div className="mt-1 flex flex-wrap gap-1">
              {goLive.env.map((e) => (
                <code key={e} className="rounded border border-border bg-panel px-1.5 py-0.5 font-mono text-text">
                  {e}
                </code>
              ))}
            </div>
            <p className="mt-1 text-muted">{goLive.note}</p>
          </>
        ) : simulatedProvider ? (
          <p className="text-muted">Simulated provider for the demo. Replace with a real vendor adapter; the waterfall interface stays the same.</p>
        ) : (
          <p className="text-muted">No live configuration available.</p>
        )}
      </div>
    </li>
  );
}

export function IntegrationsSection({
  integrations,
  ws,
}: {
  integrations: Integration[];
  ws: (Workspace & { outbound_send_enabled?: boolean }) | null;
}) {
  if (!integrations.length) return <EmptyState title="No integrations registered" />;
  const groups = [...new Set(integrations.map((i) => i.category))].sort(
    (a, b) => (CATEGORY_ORDER.indexOf(a) + 1 || 99) - (CATEGORY_ORDER.indexOf(b) + 1 || 99),
  );
  return (
    <div className="space-y-6">
      {groups.map((g) => (
        <section key={g} aria-labelledby={`cat-${g}`}>
          <h3 id={`cat-${g}`} className="mb-2 text-[11px] font-semibold uppercase tracking-wide text-muted">
            {CATEGORY_LABEL[g] ?? titleCase(g)}
          </h3>
          <ul className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
            {integrations
              .filter((i) => i.category === g)
              .map((i) => (
                <IntegrationCard key={i.provider} i={i} ws={ws} />
              ))}
          </ul>
        </section>
      ))}
      <p className="text-[11px] text-muted">
        Secrets are read from the API&apos;s environment at startup and never shown here. Outbound send is{" "}
        {ws?.outbound_send_enabled ? "enabled" : "disabled"} in this workspace: approved drafts are handed to your sending tool, not sent by
        GTMOS.
      </p>
    </div>
  );
}
