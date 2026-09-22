import { Fragment } from "react";

import { Badge } from "@/components/ui/badge";
import { Panel } from "@/components/ui/panel";
import { money, num, pct, relTime, segment } from "@/lib/format";
import { cn } from "@/lib/utils";
import type { AccountDetail, FieldConflict } from "@/lib/types";

const FIELDS: { key: string; label: string; fmt?: (v: unknown) => string }[] = [
  { key: "industry", label: "Industry" },
  { key: "employee_count", label: "Employees", fmt: (v) => num(v as number) },
  { key: "employee_growth_12m", label: "Headcount growth (12m)", fmt: (v) => pct(v as number, 0) },
  { key: "segment", label: "Segment", fmt: (v) => segment(v as string) },
  { key: "city", label: "HQ" },
  { key: "region", label: "Region" },
  { key: "funding_stage", label: "Funding stage" },
  { key: "total_funding_usd", label: "Total funding", fmt: (v) => money(v as number) },
  { key: "ai_team_size", label: "AI/ML team", fmt: (v) => num(v as number) },
  { key: "ai_open_roles", label: "Open AI/ML roles", fmt: (v) => num(v as number) },
];

function SourceBadge({ source }: { source: string }) {
  const simulated = source.startsWith("demo_");
  return (
    <Badge tone={simulated ? "warning" : "neutral"} title={simulated ? "Simulated provider" : undefined}>
      {source}
    </Badge>
  );
}

function show(v: unknown): string {
  if (v === null || v === undefined) return "—";
  if (Array.isArray(v)) return v.join(", ");
  return typeof v === "number" ? v.toLocaleString() : String(v);
}

/**
 * The answer that was rejected. Showing it is the point: a value sourced from three providers that
 * agree and a value one provider won by 0.05 confidence look identical otherwise.
 */
function ConflictRow({ conflict, span }: { conflict: FieldConflict; span: number }) {
  return (
    <tr className="border-b border-border bg-warning-soft/40 last:border-0">
      <td />
      <td colSpan={span} className="px-2 pb-2 text-[11px] text-muted">
        <span className="font-medium text-warning">{conflict.material ? "Sources disagree" : "Minor disagreement"}</span>{" "}
        {conflict.others.map((o) => (
          <span key={o.provider} className="mr-2 whitespace-nowrap">
            {o.provider} said <span className="font-medium text-text">{show(o.value)}</span>
            {o.confidence !== null && ` (${Math.round(o.confidence * 100)}%)`}
          </span>
        ))}
        {conflict.material && " — kept the stored value; this needs a human decision, not a confidence tie-break."}
      </td>
    </tr>
  );
}

/** Firmographics with field-level provenance: where each value came from, when, and how confident. */
export function FactsPanel({ data }: { data: AccountDetail }) {
  const a = data.account;
  const prov = data.provenance;
  return (
    <Panel title="Company data & provenance" description="Every enriched field records its provider, confidence and timestamp" bodyClassName="p-0">
      <table className="w-full text-xs">
        <caption className="sr-only">Account fields with provenance</caption>
        <thead className="border-b border-border text-left text-[11px] uppercase tracking-wide text-muted">
          <tr>
            <th className="px-4 py-2 font-medium">Field</th>
            <th className="px-2 py-2 font-medium">Value</th>
            <th className="px-2 py-2 font-medium">Source</th>
            <th className="px-4 py-2 text-right font-medium">Confidence</th>
          </tr>
        </thead>
        <tbody>
          {FIELDS.map((f) => {
            const v = a[f.key];
            const p = prov[f.key];
            const empty = v === null || v === undefined || v === "";
            return (
              <Fragment key={f.key}>
                <tr className={cn("border-b border-border last:border-0", p?.conflict && "border-b-0")}>
                  <td className="px-4 py-1.5 text-muted">{f.label}</td>
                  <td className="px-2 py-1.5 font-medium">
                    {empty ? <span className="text-warning">Missing</span> : f.fmt ? f.fmt(v) : String(v)}
                  </td>
                  <td className="px-2 py-1.5">{p ? <SourceBadge source={p.source} /> : <span className="text-subtle">—</span>}</td>
                  <td className="tabular px-4 py-1.5 text-right text-muted" title={p ? `Observed ${relTime(p.observed_at)}` : undefined}>
                    {p ? pct(p.confidence, 0) : "—"}
                  </td>
                </tr>
                {p?.conflict && <ConflictRow conflict={p.conflict} span={3} />}
              </Fragment>
            );
          })}
          <tr>
            <td className="px-4 py-1.5 align-top text-muted">Tech stack</td>
            <td className="px-2 py-1.5" colSpan={2}>
              <div className="flex flex-wrap gap-1">
                {a.technologies.length ? a.technologies.map((t) => <Badge key={t}>{t}</Badge>) : <span className="text-warning">Missing</span>}
              </div>
            </td>
            <td className="tabular px-4 py-1.5 text-right align-top text-muted">
              {prov.technologies ? pct(prov.technologies.confidence, 0) : "—"}
            </td>
          </tr>
        </tbody>
      </table>
      <div className="border-t border-border px-4 py-2 text-[11px] text-muted">
        Last enriched {relTime(a.last_enriched_at)} · record source {a.source}
      </div>
    </Panel>
  );
}
