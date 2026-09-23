import { duration } from "@/components/systems/format";
import { HistoryBadge } from "@/components/systems/history-badge";
import { Mono } from "@/components/systems/mono";
import { Badge, SimulatedBadge, StatusBadge } from "@/components/ui/badge";
import { EmptyState } from "@/components/ui/states";
import { Table, Td, Th, THead, Tr } from "@/components/ui/table";
import { num, relTime, titleCase } from "@/lib/format";
import type { IntegrationError, IntegrationEvent, IntegrationSyncRun } from "@/lib/types";
import { cn } from "@/lib/utils";

function SignatureBadge({ status }: { status: string }) {
  if (status === "valid") return <Badge tone="success">signed</Badge>;
  if (status === "invalid") return <Badge tone="danger">bad signature</Badge>;
  return (
    <Badge tone="warning" title="No signing secret is configured for this source, so deliveries are accepted unsigned">
      unsigned
    </Badge>
  );
}

export function EventsTable({ events }: { events: IntegrationEvent[] }) {
  if (!events.length) return <EmptyState title="No inbound deliveries" description="Nothing has arrived from this source." />;
  return (
    <Table>
      <caption className="sr-only">Recent inbound webhook deliveries</caption>
      <THead>
        <tr>
          <Th>Event</Th>
          <Th>Status</Th>
          <Th>Signature</Th>
          <Th align="right">Processing</Th>
          <Th align="right">Attempts</Th>
          <Th>Received</Th>
          <Th>Correlation</Th>
        </tr>
      </THead>
      <tbody>
        {events.map((e) => (
          <Tr key={e.id}>
            <Td className="align-top">
              <div className="flex flex-wrap items-center gap-1.5">
                <span className="font-mono text-[11px] text-text">{e.event_type}</span>
                {e.synthetic_history && <HistoryBadge />}
              </div>
              {e.error && <div className="mt-0.5 max-w-sm break-words text-[11px] text-danger">{e.error}</div>}
            </Td>
            <Td className="align-top">
              <StatusBadge status={e.status} />
              {e.duplicate_count > 0 && (
                <div className="mt-0.5 text-[11px] text-muted">{num(e.duplicate_count)} dupes absorbed</div>
              )}
            </Td>
            <Td className="align-top">
              <SignatureBadge status={e.signature_status} />
            </Td>
            <Td align="right" className="whitespace-nowrap align-top text-xs">
              {duration(e.processing_ms)}
            </Td>
            <Td align="right" className="align-top text-xs">
              {num(e.attempts)}
            </Td>
            <Td className="whitespace-nowrap align-top text-[11px] text-muted" title={e.received_at}>
              {relTime(e.received_at)}
            </Td>
            <Td className="align-top">{e.correlation_id ? <Mono>{e.correlation_id}</Mono> : "—"}</Td>
          </Tr>
        ))}
      </tbody>
    </Table>
  );
}

export function SyncsTable({ syncs }: { syncs: IntegrationSyncRun[] }) {
  if (!syncs.length)
    return <EmptyState title="No sync runs" description="This boundary does not run outbound sync jobs, or none has run yet." />;
  return (
    <Table>
      <caption className="sr-only">Recent sync runs</caption>
      <THead>
        <tr>
          <Th>Job</Th>
          <Th>Status</Th>
          <Th align="right">Changed</Th>
          <Th align="right">Failed</Th>
          <Th align="right">Skipped</Th>
          <Th align="right">Retries</Th>
          <Th align="right">Duration</Th>
          <Th>Started</Th>
          <Th>Correlation</Th>
        </tr>
      </THead>
      <tbody>
        {syncs.map((s) => (
          <Tr key={s.id}>
            <Td className="align-top">
              <div className="flex flex-wrap items-center gap-1.5">
                <span className="font-mono text-[11px] text-text">{s.job}</span>
                {s.is_simulated && <SimulatedBadge />}
              </div>
              <div className="mt-0.5 text-[11px] text-muted">
                {titleCase(s.direction)} · {s.object_type}
              </div>
              {s.error && <div className="mt-0.5 max-w-sm break-words text-[11px] text-danger">{s.error}</div>}
            </Td>
            <Td className="align-top">
              <StatusBadge status={s.status} />
            </Td>
            <Td align="right" className="align-top text-xs">
              {num(s.records_changed)}
            </Td>
            <Td align="right" className={cn("align-top text-xs", s.records_failed > 0 && "text-danger")}>
              {num(s.records_failed)}
            </Td>
            <Td align="right" className="align-top text-xs text-muted">
              {num(s.records_skipped)}
            </Td>
            <Td align="right" className="align-top text-xs">
              {num(s.retries)}
            </Td>
            <Td align="right" className="whitespace-nowrap align-top text-xs">
              {duration(s.duration_ms)}
            </Td>
            <Td className="whitespace-nowrap align-top text-[11px] text-muted" title={s.started_at}>
              {relTime(s.started_at)}
            </Td>
            <Td className="align-top">{s.correlation_id ? <Mono>{s.correlation_id}</Mono> : "—"}</Td>
          </Tr>
        ))}
      </tbody>
    </Table>
  );
}

export function ErrorList({ errors }: { errors: IntegrationError[] }) {
  if (!errors.length)
    return <EmptyState title="No errors recorded" description="Every delivery and sync run in this window succeeded." />;
  return (
    <ul className="divide-y divide-border">
      {errors.map((e, idx) => (
        <li key={`${e.kind}-${e.at}-${idx}`} className="px-4 py-2.5">
          <div className="flex flex-wrap items-center gap-1.5 text-xs">
            <span className="font-medium text-text">{e.label}</span>
            <StatusBadge status={e.status} />
            <Badge>{e.kind === "webhook" ? "inbound" : "sync"}</Badge>
            <span className="text-[11px] text-muted">{relTime(e.at)}</span>
          </div>
          <p className="mt-0.5 break-words text-[11px] text-danger">{e.message ?? "No error message recorded"}</p>
          {e.correlation_id && <Mono>{e.correlation_id}</Mono>}
        </li>
      ))}
    </ul>
  );
}
