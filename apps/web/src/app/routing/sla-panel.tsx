import Link from "next/link";

import { Badge } from "@/components/ui/badge";
import { Panel } from "@/components/ui/panel";
import { StatCell, StatGrid } from "@/components/ui/stat";
import { EmptyState } from "@/components/ui/states";
import { Table, Td, Th, THead, Tr } from "@/components/ui/table";
import { num, pct } from "@/lib/format";

import type { SlaReport } from "./types";

/**
 * Speed to lead. Routing that picks the right owner and then leaves the account untouched for three
 * days has not worked, so the SLA is reported next to the rules that promised it — and a late touch is
 * kept separate from no touch at all, because only one of those is a process problem.
 */
export function SlaPanel({ sla }: { sla: SlaReport | null }) {
  if (!sla) return null;
  if (!sla.decisions_with_sla) {
    return (
      <Panel title="Speed to first touch" description="The SLA each routing rule promised, against what actually happened">
        <EmptyState
          title="No routed accounts carry an SLA yet"
          description={sla.note ?? "Give a routing rule an SLA and assignments will be measured against it."}
        />
      </Panel>
    );
  }
  // The hit rate is measured over assignments whose clock has run out; a pending one is not a miss.
  const decided = sla.met + sla.late + sla.untouched;
  return (
    <Panel
      title="Speed to first touch"
      description={`${num(sla.decisions_with_sla)} lead-event assignments with an SLA over ${sla.window_days} days`}
      bodyClassName="p-0"
    >
      <div className="p-4">
        <StatGrid>
          <StatCell
            label="Met the SLA"
            value={sla.hit_rate != null ? pct(sla.hit_rate, 0) : "—"}
            sub={`${num(sla.met)} of ${num(decided)} whose clock has run out`}
          />
          <StatCell label="Touched late" value={num(sla.late)} sub="worked, but after the promise" />
          <StatCell
            label="Never touched"
            value={num(sla.untouched)}
            sub={sla.untouched ? "the clock ran out and nobody reached out" : "none"}
          />
          <StatCell
            label="Median time to first touch"
            value={sla.median_hours_to_first_touch != null ? `${num(sla.median_hours_to_first_touch, 1)}h` : "—"}
            sub="assignment → first outbound touch"
          />
        </StatGrid>
      </div>

      {sla.by_rule.length > 0 && (
        <Table>
          <caption className="sr-only">SLA performance by routing rule</caption>
          <THead>
            <tr>
              <Th>Rule</Th>
              <Th align="right">Assignments</Th>
              <Th align="right">Met</Th>
              <Th align="right">Late</Th>
              <Th align="right">Never touched</Th>
              <Th align="right">Still pending</Th>
            </tr>
          </THead>
          <tbody>
            {sla.by_rule.map((r) => (
              <Tr key={r.rule}>
                <Td className="text-xs font-medium">{r.rule}</Td>
                <Td align="right" className="text-xs">
                  {num(r.n)}
                </Td>
                <Td align="right" className="text-xs">
                  {num(r.met)}
                </Td>
                <Td align="right" className="text-xs">
                  {r.late ? <Badge tone="warning">{num(r.late)}</Badge> : <span className="text-muted">0</span>}
                </Td>
                <Td align="right" className="text-xs">
                  {r.untouched ? <Badge tone="danger">{num(r.untouched)}</Badge> : <span className="text-muted">0</span>}
                </Td>
                <Td align="right" className="text-xs text-muted">
                  {num(r.pending)}
                </Td>
              </Tr>
            ))}
          </tbody>
        </Table>
      )}

      {sla.worst.length > 0 && (
        <div className="border-t border-border p-4">
          <h3 className="text-xs font-medium text-text">Worst offenders</h3>
          <ul className="mt-2 flex flex-wrap gap-1.5">
            {sla.worst.slice(0, 10).map((w) => (
              <li key={w.account_id}>
                <Link
                  href={`/accounts/${w.account_id}`}
                  className="inline-flex items-center gap-1.5 rounded-md border border-border px-2 py-1 text-[11px] hover:bg-panel-2"
                >
                  <span className="text-text">{w.account ?? "Account"}</span>
                  <span className={w.state === "untouched" ? "text-danger" : "text-warning"}>
                    {w.state === "untouched" ? "never touched" : "late"}
                  </span>
                  {w.overdue_hours > 0 && <span className="tabular text-muted">{num(w.overdue_hours, 0)}h over</span>}
                </Link>
              </li>
            ))}
          </ul>
        </div>
      )}

      {sla.definition && <p className="border-t border-border px-4 py-3 text-[11px] text-muted">{sla.definition}</p>}
    </Panel>
  );
}
