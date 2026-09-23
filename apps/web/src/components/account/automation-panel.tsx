import Link from "next/link";

import { Badge, SimulatedBadge, StatusBadge } from "@/components/ui/badge";
import { Panel } from "@/components/ui/panel";
import { EmptyState } from "@/components/ui/states";
import { dateTime, relTime, titleCase } from "@/lib/format";
import type { AccountDetail } from "@/lib/types";

function show(v: unknown): string {
  if (v === null || v === undefined) return "—";
  if (Array.isArray(v)) return v.join(", ");
  if (typeof v === "object") return JSON.stringify(v);
  return String(v);
}

export function AutomationPanel({ data }: { data: AccountDetail }) {
  const attempts = data.enrichment.latest_attempts;
  const fields = [...new Set(attempts.map((a) => a.field))];
  const providers = [...new Set(attempts.map((a) => a.provider))];
  return (
    <div className="space-y-4">
      <Panel title="Workflow runs" bodyClassName="p-0">
        {data.workflow_runs.length === 0 ? (
          <EmptyState title="No workflow runs for this account" />
        ) : (
          <ul className="divide-y divide-border">
            {data.workflow_runs.map((r) => (
              <li key={r.id} className="flex flex-wrap items-center gap-2 px-4 py-2 text-xs">
                <StatusBadge status={r.status} />
                <Link href={`/workflows/runs/${r.id}`} className="font-medium hover:underline">
                  {r.workflow}
                </Link>
                {r.synthetic_history && <Badge title="Seeded illustrative history">history (synthetic)</Badge>}
                <span className="text-muted">{r.trigger}</span>
                {r.error && <span className="text-danger">{r.error}</span>}
                <span className="ml-auto text-muted">{relTime(r.created_at)}</span>
              </li>
            ))}
          </ul>
        )}
      </Panel>

      <Panel title="Routing decisions" description="Every assignment is explained, including rules that lost" bodyClassName="p-0">
        {data.routing_decisions.length === 0 ? (
          <EmptyState title="Never routed" />
        ) : (
          <ul className="divide-y divide-border">
            {data.routing_decisions.map((d) => (
              <li key={d.id} className="px-4 py-2.5 text-xs">
                <div className="flex flex-wrap items-center gap-2">
                  <StatusBadge status={d.outcome} />
                  <span className="font-medium">{d.assigned_to ?? "No owner"}</span>
                  <span className="text-muted">· {d.trigger}</span>
                  {d.conflicts.length > 0 && <Badge tone="warning">{d.conflicts.length} conflict(s) resolved</Badge>}
                  <span className="ml-auto text-muted">{dateTime(d.decided_at)}</span>
                </div>
                <ul className="mt-1 space-y-0.5 text-muted">
                  {d.explanation.map((e, i) => (
                    <li key={i}>· {e}</li>
                  ))}
                </ul>
              </li>
            ))}
          </ul>
        )}
      </Panel>

      <Panel
        title="Experiments"
        description="Which tests this account is in, the arm it landed in, and what it did afterwards"
        bodyClassName="p-0"
      >
        {data.experiments.length === 0 ? (
          <div className="px-4 py-3 text-xs text-subtle">
            This account is not enrolled in any experiment. Assignment is deterministic, so it will land in the
            same arm whenever it does enter one.
          </div>
        ) : (
          <ul className="divide-y divide-border">
            {data.experiments.map((e) => (
              <li key={e.experiment_key} className="px-4 py-2.5 text-xs">
                <div className="flex flex-wrap items-center gap-2">
                  <Link href={`/experiments/${e.experiment_key}`} className="font-medium text-accent-text hover:underline">
                    {e.experiment}
                  </Link>
                  <Badge tone={e.is_control ? "neutral" : "accent"}>{e.variant}</Badge>
                  <span className="text-muted">{titleCase(e.status)}</span>
                  <span className="ml-auto text-muted">{dateTime(e.assigned_at)}</span>
                </div>
                <div className="mt-1 text-[11px] text-muted">
                  {e.outcomes.length ? (
                    <>Recorded outcomes: {e.outcomes.map((o) => titleCase(o)).join(", ")}</>
                  ) : (
                    <>No outcome recorded yet for this account.</>
                  )}
                </div>
              </li>
            ))}
          </ul>
        )}
      </Panel>

      <Panel
        title="Enrichment waterfall (latest run)"
        description="Per field, providers are tried in order until one returns a confident value"
        bodyClassName="p-0"
      >
        {attempts.length === 0 ? (
          <EmptyState title="No enrichment runs yet" description="Use Enrich to run the waterfall." />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead className="border-b border-border text-left text-[11px] uppercase tracking-wide text-muted">
                <tr>
                  <th className="px-4 py-2 font-medium">Field</th>
                  {providers.map((p) => (
                    <th key={p} className="px-2 py-2 font-medium">
                      {p}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {fields.map((f) => (
                  <tr key={f} className="border-b border-border last:border-0">
                    <td className="px-4 py-1.5 text-muted">{titleCase(f)}</td>
                    {providers.map((p) => {
                      const a = attempts.find((x) => x.field === f && x.provider === p);
                      if (!a) return <td key={p} className="px-2 py-1.5 text-subtle">·</td>;
                      const tone =
                        a.outcome === "hit" ? "success" : a.outcome === "error" ? "danger" : a.outcome === "low_confidence" ? "warning" : "neutral";
                      return (
                        <td key={p} className="px-2 py-1.5" title={a.error ?? show(a.value)}>
                          <Badge tone={tone}>
                            {a.position + 1}. {a.outcome.replace("_", " ")}
                          </Badge>
                          {a.outcome === "hit" && <div className="mt-0.5 max-w-40 truncate text-[11px] text-muted">{show(a.value)}</div>}
                        </td>
                      );
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Panel>

      <Panel title="CRM sync" description="What GTMOS last pushed to the CRM (reverse ETL)" actions={data.crm_sync?.is_simulated ? <SimulatedBadge /> : null}>
        {data.crm_sync ? (
          <div className="text-xs">
            <div className="text-muted">
              External id <span className="font-mono text-text">{data.crm_sync.external_id}</span> · synced {relTime(data.crm_sync.last_synced_at)}
            </div>
            <dl className="mt-2 grid grid-cols-1 gap-x-6 gap-y-1 sm:grid-cols-2">
              {Object.entries(data.crm_sync.last_payload).map(([k, v]) => (
                <div key={k} className="flex justify-between gap-3 border-b border-border py-1">
                  <dt className="font-mono text-[11px] text-muted">{k}</dt>
                  <dd className="truncate text-right" title={show(v)}>
                    {show(v)}
                  </dd>
                </div>
              ))}
            </dl>
          </div>
        ) : (
          <EmptyState title="Not synced yet" description="Only A/B/C accounts are pushed by the reverse-ETL job." />
        )}
      </Panel>

      <Panel title="Audit trail" bodyClassName="p-0">
        {data.audit.length === 0 ? (
          <EmptyState title="No audited changes" />
        ) : (
          <ul className="divide-y divide-border">
            {data.audit.map((e) => (
              <li key={e.id} className="px-4 py-2 text-xs">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="font-mono text-[11px]">{e.action}</span>
                  <Badge>{e.actor_type}</Badge>
                  <span className="text-muted">{e.actor}</span>
                  <span className="ml-auto text-muted">{dateTime(e.occurred_at)}</span>
                </div>
                {(e.before || e.after) && (
                  <div className="mt-0.5 break-all font-mono text-[11px] text-muted">
                    {e.before ? JSON.stringify(e.before) : "∅"} → {e.after ? JSON.stringify(e.after) : "∅"}
                  </div>
                )}
                {e.reason && <div className="mt-0.5 text-muted">{e.reason}</div>}
              </li>
            ))}
          </ul>
        )}
      </Panel>
    </div>
  );
}
