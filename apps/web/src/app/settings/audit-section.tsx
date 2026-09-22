import { ChipLink } from "@/components/insights/chip-link";
import type { AuditResponse } from "@/components/insights/types";
import { Badge } from "@/components/ui/badge";
import { EmptyState, ErrorState } from "@/components/ui/states";
import { Table, Td, Th, THead, Tr } from "@/components/ui/table";
import { dateTime, num } from "@/lib/format";
import type { AuditEvent } from "@/lib/types";

const ACTOR_TYPES = ["user", "system", "workflow", "integration"];

function short(v: unknown, max = 36): string {
  if (v === null || v === undefined) return "∅";
  const s = typeof v === "object" ? JSON.stringify(v) : String(v);
  const flat = s.replace(/\s+/g, " ");
  return flat.length > max ? `${flat.slice(0, max - 1)}…` : flat;
}

/** Compact before → after: only keys whose value changed (or all keys of a creation). */
function Diff({ before, after }: { before: AuditEvent["before"]; after: AuditEvent["after"] }) {
  if (!before && !after) return <span className="text-subtle">—</span>;
  const keys = Array.from(new Set([...Object.keys(before ?? {}), ...Object.keys(after ?? {})]));
  const changed = before
    ? keys.filter((k) => JSON.stringify(before[k]) !== JSON.stringify(after?.[k]))
    : keys;
  if (!changed.length) return <span className="text-subtle">no field changes</span>;
  const shown = changed.slice(0, 4);
  return (
    <ul className="space-y-0.5 font-mono text-[11px]">
      {shown.map((k) => (
        <li key={k} className="flex min-w-0 flex-wrap items-baseline gap-x-1">
          <span className="text-muted">{k}:</span>
          {before && (
            <>
              <span className="text-danger line-through decoration-danger/40" title={short(before[k], 500)}>
                {short(before[k])}
              </span>
              <span className="text-subtle" aria-label="changed to">
                →
              </span>
            </>
          )}
          <span className="text-text" title={short(after?.[k], 500)}>
            {short(after?.[k])}
          </span>
        </li>
      ))}
      {changed.length > shown.length && <li className="text-subtle">+{changed.length - shown.length} more</li>}
    </ul>
  );
}

function href(params: { action?: string; actor_type?: string }) {
  const q = new URLSearchParams({ tab: "audit" });
  if (params.action) q.set("action", params.action);
  if (params.actor_type) q.set("actor_type", params.actor_type);
  return `/settings?${q.toString()}#audit`;
}

export function AuditSection({
  audit,
  action,
  actorType,
}: {
  audit: AuditResponse | null;
  action?: string;
  actorType?: string;
}) {
  if (!audit) return <ErrorState title="Couldn't load the audit log" />;
  const prefixes = Object.entries(audit.actions).reduce<Record<string, number>>((acc, [a, n]) => {
    const p = a.split(".")[0];
    acc[p] = (acc[p] ?? 0) + n;
    return acc;
  }, {});
  const prefixList = Object.entries(prefixes).sort((a, b) => b[1] - a[1]);
  const total = Object.values(audit.actions).reduce((a, b) => a + b, 0);

  return (
    <div id="audit" className="space-y-3">
      <div className="space-y-2 rounded-lg border border-border bg-panel p-3">
        <div className="flex flex-wrap items-center gap-1.5">
          <span className="w-16 text-[11px] font-medium text-muted">Action</span>
          <ChipLink href={href({ actor_type: actorType })} active={!action}>
            All <span className="ml-1 text-subtle">{num(total)}</span>
          </ChipLink>
          {prefixList.map(([p, n]) => (
            <ChipLink key={p} href={href({ action: p, actor_type: actorType })} active={action === p}>
              {p}.* <span className="ml-1 text-subtle">{num(n)}</span>
            </ChipLink>
          ))}
        </div>
        <div className="flex flex-wrap items-center gap-1.5">
          <span className="w-16 text-[11px] font-medium text-muted">Actor</span>
          <ChipLink href={href({ action })} active={!actorType}>
            Any
          </ChipLink>
          {ACTOR_TYPES.map((t) => (
            <ChipLink key={t} href={href({ action, actor_type: t })} active={actorType === t}>
              {t}
            </ChipLink>
          ))}
        </div>
      </div>

      <div className="rounded-lg border border-border bg-panel">
        {audit.items.length ? (
          <Table>
            <THead>
              <tr>
                <Th>When</Th>
                <Th>Actor</Th>
                <Th>Action</Th>
                <Th>Entity</Th>
                <Th>Change</Th>
                <Th>Reason</Th>
              </tr>
            </THead>
            <tbody>
              {audit.items.map((e) => (
                <Tr key={e.id}>
                  <Td className="whitespace-nowrap align-top text-xs text-muted">{dateTime(e.occurred_at)}</Td>
                  <Td className="align-top">
                    <div className="max-w-44 truncate text-xs" title={e.actor}>
                      {e.actor}
                    </div>
                    <Badge className="mt-0.5">{e.actor_type}</Badge>
                  </Td>
                  <Td className="whitespace-nowrap align-top font-mono text-xs">{e.action}</Td>
                  <Td className="align-top text-xs">
                    <div>{e.entity_type}</div>
                    {e.entity_id && (
                      <div className="font-mono text-[11px] text-muted" title={e.entity_id}>
                        {e.entity_id.slice(0, 8)}…
                      </div>
                    )}
                  </Td>
                  <Td className="min-w-56 max-w-md align-top">
                    <Diff before={e.before} after={e.after} />
                  </Td>
                  <Td className="max-w-56 align-top text-xs text-muted">
                    {e.reason ?? "—"}
                    {e.correlation_id && (
                      <div className="font-mono text-[11px] text-subtle" title="Correlation ID: joins this event to its workflow run and API logs">
                        {e.correlation_id}
                      </div>
                    )}
                  </Td>
                </Tr>
              ))}
            </tbody>
          </Table>
        ) : (
          <EmptyState title="No audit events match" description="Try a different action or actor filter." />
        )}
      </div>
      <p className="text-[11px] text-muted">
        Showing the latest {num(audit.items.length)} events. Every write in GTMOS (user, system, workflow or integration) records an
        append-only audit event with before/after values.
      </p>
    </div>
  );
}
