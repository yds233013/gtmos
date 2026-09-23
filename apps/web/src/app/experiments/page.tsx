import Link from "next/link";

import { metricLabel, VerdictBadge } from "@/components/insights/experiment-ui";
import { Badge, DemoBadge } from "@/components/ui/badge";
import { PageHeader } from "@/components/ui/page-header";
import { Panel } from "@/components/ui/panel";
import { EmptyState, ErrorState } from "@/components/ui/states";
import { Table, Td, Th, THead, Tr } from "@/components/ui/table";
import { api, ApiError } from "@/lib/api";
import { date, num } from "@/lib/format";

import { ActionBadge } from "./guardrail-ui";
import type { GuardedExperimentRow } from "./types";

export const metadata = { title: "Experiments" };

export default async function ExperimentsPage() {
  let rows: GuardedExperimentRow[] | null = null;
  let error: string | null = null;
  try {
    rows = await api<GuardedExperimentRow[]>("/experiments");
  } catch (e) {
    error = e instanceof ApiError ? e.message : "Failed to load experiments";
  }

  return (
    <div className="space-y-4">
      <PageHeader
        title="Experiments"
        eyebrow={<DemoBadge />}
        description="Pre-registered A/B tests on outbound messaging. Units are assigned by a deterministic hash, each test declares its primary metric and minimum sample up front, and no winner is declared until the sample is reached."
      />

      {error ? (
        <ErrorState title="Couldn't load experiments" message={error} />
      ) : (
        <Panel bodyClassName="p-0">
          {rows && rows.length ? (
            <Table>
              <THead>
                <tr>
                  <Th>Experiment</Th>
                  <Th>Status</Th>
                  <Th>Primary metric</Th>
                  <Th align="right">Units</Th>
                  <Th>Verdict</Th>
                  <Th>Recommendation</Th>
                  <Th>Dates</Th>
                </tr>
              </THead>
              <tbody>
                {rows.map((e) => (
                  <Tr key={e.id}>
                    <Td className="min-w-64">
                      <Link href={`/experiments/${e.key}`} className="font-medium hover:underline">
                        {e.name}
                      </Link>
                      <div className="text-xs text-muted">{e.campaign ? `Campaign: ${e.campaign}` : "No campaign"}</div>
                    </Td>
                    <Td>
                      <Badge tone={e.status === "running" ? "info" : "neutral"}>{e.status}</Badge>
                    </Td>
                    <Td className="text-xs">{metricLabel(e.primary_metric)}</Td>
                    <Td align="right">
                      {num(e.units)} <span className="text-xs text-muted">{e.unit}s</span>
                    </Td>
                    <Td>
                      <VerdictBadge verdict={e.verdict} />
                    </Td>
                    <Td>
                      <ActionBadge action={e.action} />
                      {e.guardrail_breaches.length > 0 && (
                        <div className="mt-1 text-[11px] text-danger">
                          {e.guardrail_breaches.map((m) => metricLabel(m).toLowerCase()).join(", ")} breached
                        </div>
                      )}
                    </Td>
                    <Td className="whitespace-nowrap text-xs text-muted">
                      {date(e.started_at)} – {e.ended_at ? date(e.ended_at) : "running"}
                    </Td>
                  </Tr>
                ))}
              </tbody>
            </Table>
          ) : (
            <EmptyState title="No experiments yet" description="Experiments attach to campaigns and appear here once units are assigned." />
          )}
        </Panel>
      )}
      <p className="text-[11px] text-muted">
        Verdicts come from a two-proportion z-test (α = 0.05) on the primary metric. &ldquo;Insufficient sample&rdquo; means the test has
        not reached its pre-registered minimum; it is not a result.
      </p>
    </div>
  );
}
