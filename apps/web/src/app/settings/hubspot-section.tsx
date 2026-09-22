import { ArrowRight, KeyRound } from "lucide-react";

import { ActionButton } from "@/components/ui/action-button";
import { Badge, SimulatedBadge } from "@/components/ui/badge";
import { EmptyState, ErrorState } from "@/components/ui/states";
import { Table, Td, Th, THead, Tr } from "@/components/ui/table";
import type { HubspotMapping, ReverseEtlPreview, SimulatedObjects } from "@/components/insights/types";
import { dateTime, num, relTime } from "@/lib/format";

export function MappingSection({ mapping }: { mapping: HubspotMapping | null }) {
  if (!mapping) return <ErrorState title="Couldn't load the HubSpot mapping" />;
  return (
    <div className="space-y-4">
      <div className="grid gap-4 lg:grid-cols-3">
        <div className="rounded-lg border border-border bg-panel lg:col-span-2">
          <h3 className="border-b border-border px-4 py-3 text-sm font-semibold text-text">Object mapping</h3>
          <Table>
            <THead>
              <tr>
                <Th>GTMOS</Th>
                <Th />
                <Th>HubSpot object</Th>
                <Th>Upsert key</Th>
              </tr>
            </THead>
            <tbody>
              {Object.entries(mapping.objects).map(([ours, theirs]) => (
                <Tr key={ours}>
                  <Td className="font-medium">{ours}</Td>
                  <Td className="w-6 text-subtle">
                    <ArrowRight className="size-3.5" aria-label="maps to" />
                  </Td>
                  <Td className="font-mono text-xs">{theirs}</Td>
                  <Td>
                    <code className="rounded bg-panel-2 px-1.5 py-0.5 font-mono text-[11px] text-text">{mapping.id_properties[theirs] ?? "—"}</code>
                  </Td>
                </Tr>
              ))}
            </tbody>
          </Table>
        </div>
        <div className="rounded-lg border border-accent/30 bg-accent-soft p-4 text-xs">
          <div className="flex items-center gap-2 font-medium text-accent-text">
            <KeyRound className="size-4" aria-hidden />
            Why upsert on gtmos_account_id, not domain
          </div>
          <p className="mt-2 text-text">
            HubSpot does not enforce domain uniqueness on companies: two records can share a domain, and the domain can be blank or change
            after a rebrand. Upserting by domain would silently update the wrong record or create duplicates.
          </p>
          <p className="mt-2 text-text">
            GTMOS writes its own ID to a custom property marked <span className="font-medium">unique</span> in HubSpot, so every sync is
            idempotent: re-running it updates the same record. Contacts key on email, which HubSpot does enforce as unique.
          </p>
        </div>
      </div>

      <div className="grid gap-4 lg:grid-cols-3">
        {Object.entries(mapping.custom_properties).map(([obj, props]) => (
          <div key={obj} className="rounded-lg border border-border bg-panel">
            <h3 className="flex items-center justify-between border-b border-border px-4 py-3 text-sm font-semibold text-text">
              <span>
                Custom properties · <span className="font-mono text-xs">{obj}</span>
              </span>
              <span className="text-xs font-normal text-muted">{props.length}</span>
            </h3>
            <ul className="divide-y divide-border text-xs">
              {props.map((p) => (
                <li key={p.name} className="flex items-center justify-between gap-2 px-4 py-1.5">
                  <span className="min-w-0">
                    <span className="block truncate font-mono text-[11px] text-text">{p.name}</span>
                    <span className="block truncate text-[11px] text-muted">{p.label}</span>
                  </span>
                  <span className="flex shrink-0 items-center gap-1">
                    {p.hasUniqueValue && <Badge tone="accent">unique</Badge>}
                    <Badge>{p.type}</Badge>
                  </span>
                </li>
              ))}
            </ul>
          </div>
        ))}
      </div>
    </div>
  );
}

function PropValue({ v }: { v: unknown }) {
  if (v === null || v === undefined || v === "") return <span className="text-subtle">—</span>;
  const s = typeof v === "object" ? JSON.stringify(v) : String(v);
  return (
    <span className="block max-w-56 truncate" title={s}>
      {s}
    </span>
  );
}

export function ReverseEtlSection({ preview, objects }: { preview: ReverseEtlPreview | null; objects: SimulatedObjects | null }) {
  const simulated = preview?.destination_mode !== "live";
  const changed = preview ? Object.entries(preview.changed_field_counts).sort((a, b) => b[1] - a[1]) : [];
  const propCols = ["gtmos_score_grade", "gtmos_icp_score", "gtmos_intent_score", "gtmos_account_tier", "gtmos_next_best_action", "gtmos_last_signal"];
  return (
    <div className="space-y-4">
      {preview ? (
        <div className="rounded-lg border border-border bg-panel">
          <div className="flex flex-col gap-3 border-b border-border px-4 py-3 sm:flex-row sm:items-start sm:justify-between">
            <div>
              <h3 className="flex flex-wrap items-center gap-2 text-sm font-semibold text-text">
                Reverse ETL: accounts → HubSpot companies
                {simulated ? <SimulatedBadge /> : <Badge tone="success">LIVE</Badge>}
              </h3>
              <p className="mt-0.5 text-xs text-muted">
                Dry run of the next sync. Only changed fields are written; unchanged records are skipped.
                {preview.last_run &&
                  ` Last run ${relTime(preview.last_run.finished_at)} (${preview.last_run.status}${preview.last_run.is_simulated ? ", simulated" : ""}).`}
              </p>
            </div>
            <ActionButton path="/integrations/hubspot/reverse-etl/run" variant="primary" confirmLabel={simulated ? "Confirm simulated sync" : "Confirm LIVE write to HubSpot"}>
              {simulated ? "Run sync (simulated)" : "Run sync"}
            </ActionButton>
          </div>
          <div className="grid grid-cols-2 gap-px bg-border sm:grid-cols-4">
            {[
              ["Considered", preview.considered],
              ["Would create", preview.would_create],
              ["Would update", preview.would_update],
              ["Unchanged", preview.unchanged],
            ].map(([label, value]) => (
              <div key={label as string} className="bg-panel px-4 py-3">
                <div className="text-xs text-muted">{label}</div>
                <div className="tabular mt-1 text-lg font-semibold text-text">{num(value as number)}</div>
              </div>
            ))}
          </div>
          <div className="space-y-3 border-t border-border px-4 py-3">
            {changed.length > 0 && (
              <div className="flex flex-wrap items-center gap-1.5 text-xs">
                <span className="text-muted">Changed fields:</span>
                {changed.map(([f, n]) => (
                  <span key={f} className="rounded border border-border bg-panel-2 px-1.5 py-0.5 font-mono text-[11px] text-text">
                    {f} <span className="text-muted">× {num(n)}</span>
                  </span>
                ))}
              </div>
            )}
            {preview.sample.length ? (
              <div className="overflow-hidden rounded border border-border">
                <Table>
                  <THead>
                    <tr>
                      <Th>Account</Th>
                      <Th>Change</Th>
                      <Th>Fields</Th>
                    </tr>
                  </THead>
                  <tbody>
                    {preview.sample.map((s) => (
                      <Tr key={s.account_id}>
                        <Td className="font-medium">{s.name}</Td>
                        <Td>{s.is_new ? <Badge tone="info">create</Badge> : <Badge>update</Badge>}</Td>
                        <Td className="text-xs">
                          <div className="flex flex-wrap gap-1">
                            {s.changed_fields.map((f) => (
                              <span key={f} className="font-mono text-[11px]" title={String(s.properties[f] ?? "")}>
                                {f}
                                <span className="text-muted">={String(s.properties[f] ?? "∅").slice(0, 24)}</span>
                              </span>
                            ))}
                          </div>
                        </Td>
                      </Tr>
                    ))}
                  </tbody>
                </Table>
              </div>
            ) : (
              <p className="text-xs text-muted">
                Everything is in sync: all {num(preview.considered)} eligible accounts match the CRM. Rescore accounts or change the ICP and
                the next sync will pick up the differences.
              </p>
            )}
          </div>
        </div>
      ) : (
        <ErrorState title="Couldn't load the reverse-ETL preview" />
      )}

      <div className="rounded-lg border border-border bg-panel">
        <div className="flex flex-wrap items-start justify-between gap-2 border-b border-border px-4 py-3">
          <div>
            <h3 className="flex items-center gap-2 text-sm font-semibold text-text">
              CRM objects {objects?.simulated !== false && <SimulatedBadge />}
            </h3>
            <p className="mt-0.5 text-xs text-muted">{objects?.note ?? "Records written by the HubSpot adapter."}</p>
          </div>
          {objects && (
            <span className="text-xs text-muted">
              {Object.entries(objects.counts)
                .map(([k, v]) => `${num(v)} ${k}`)
                .join(" · ")}
            </span>
          )}
        </div>
        {objects ? (
          objects.items.length ? (
            <Table>
              <THead>
                <tr>
                  <Th>Company</Th>
                  <Th>HubSpot ID</Th>
                  {propCols.map((c) => (
                    <Th key={c}>{c.replace("gtmos_", "")}</Th>
                  ))}
                  <Th>Updated</Th>
                </tr>
              </THead>
              <tbody>
                {objects.items.map((o) => (
                  <Tr key={o.id}>
                    <Td>
                      <div className="font-medium">{String(o.properties.name ?? "—")}</div>
                      <div className="font-mono text-[11px] text-muted" title="gtmos_account_id (unique upsert key)">
                        {o.unique_key.slice(0, 8)}…
                      </div>
                    </Td>
                    <Td className="font-mono text-xs">{o.external_id}</Td>
                    {propCols.map((c) => (
                      <Td key={c} className="text-xs">
                        <PropValue v={o.properties[c]} />
                      </Td>
                    ))}
                    <Td className="whitespace-nowrap text-xs text-muted">{dateTime(o.updated_at)}</Td>
                  </Tr>
                ))}
              </tbody>
            </Table>
          ) : (
            <EmptyState title="No CRM objects yet" description="Run a sync to populate the simulated CRM store." />
          )
        ) : (
          <div className="p-4">
            <ErrorState title="Couldn't load CRM objects" />
          </div>
        )}
      </div>
    </div>
  );
}
