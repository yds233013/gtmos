import { money, num, pct } from "@/lib/format";
import { cn } from "@/lib/utils";

/**
 * Renders an arbitrary evidence object (numbers, maps, lists, rows) as a readable key/value list,
 * so every headline on the page can be traced back to the raw values that produced it.
 * Pure server-renderable markup; no client JS.
 */

const ACRONYMS: Record<string, string> = {
  ab: "A/B",
  ai: "AI",
  crm: "CRM",
  pql: "PQL",
  id: "ID",
  ids: "IDs",
  icp: "ICP",
  llm: "LLM",
  url: "URL",
};

export function humanizeKey(key: string): string {
  const windowMatch = key.match(/^(.*)_(\d+[dhw])$/);
  // Unit suffixes are rendered with the value ("95 h"), so drop them from the label.
  const base = (windowMatch ? windowMatch[1] : key).replace(/_hours?$/, "");
  const words = base.split("_").map((w) => ACRONYMS[w.toLowerCase()] ?? w);
  let label = words.join(" ");
  label = label.charAt(0).toUpperCase() + label.slice(1);
  return windowMatch ? `${label} (${windowMatch[2]})` : label;
}

function isRateKey(key: string) {
  return /(rate|coverage|share|ratio|pct|percent)/i.test(key);
}

export function formatEvidenceNumber(key: string, value: number): string {
  if (/(pipeline|revenue|amount|usd|arr)/i.test(key)) return money(value);
  if (isRateKey(key) && Math.abs(value) <= 1) return pct(value, 1);
  if (/hours?$/i.test(key)) return `${num(value, 1)} h`;
  if (/days?$/i.test(key) && !/_\d+d$/.test(key)) return `${num(value, 1)} d`;
  if (/credits/i.test(key)) return num(value, 1);
  return num(value, Number.isInteger(value) ? 0 : 2);
}

type Json = null | boolean | number | string | Json[] | { [k: string]: Json };

function isPlainObject(v: unknown): v is Record<string, Json> {
  return typeof v === "object" && v !== null && !Array.isArray(v);
}

function Scalar({ k, v }: { k: string; v: unknown }) {
  if (v === null || v === undefined) return <span className="text-subtle">n/a</span>;
  if (typeof v === "number") return <span className="tabular font-medium text-text">{formatEvidenceNumber(k, v)}</span>;
  if (typeof v === "boolean") return <span className="font-medium text-text">{v ? "Yes" : "No"}</span>;
  return <span className="text-text">{String(v)}</span>;
}

/** Map of name → fraction (0..1): small horizontal bars. */
function CoverageBars({ k, obj }: { k: string; obj: Record<string, number> }) {
  return (
    <ul className="space-y-1.5" aria-label={humanizeKey(k)}>
      {Object.entries(obj).map(([name, value]) => {
        const tone = value >= 0.95 ? "bg-success" : value >= 0.85 ? "bg-warning" : "bg-danger";
        return (
          <li key={name} className="grid grid-cols-[minmax(0,8rem)_1fr_3.5rem] items-center gap-2 text-xs">
            <span className="truncate text-muted" title={name}>
              {humanizeKey(name)}
            </span>
            <span
              className="h-1.5 overflow-hidden rounded-full bg-panel-2"
              role="meter"
              aria-valuemin={0}
              aria-valuemax={1}
              aria-valuenow={value}
              aria-label={`${humanizeKey(name)} coverage`}
            >
              <span className={cn("block h-full rounded-full", tone)} style={{ width: `${Math.max(0, Math.min(1, value)) * 100}%` }} />
            </span>
            <span className="tabular text-right font-medium text-text">{pct(value, 1)}</span>
          </li>
        );
      })}
    </ul>
  );
}

/** Map of name → count: compact ranked list with proportional bars. */
function CountMap({ k, obj }: { k: string; obj: Record<string, number> }) {
  const entries = Object.entries(obj).sort((a, b) => b[1] - a[1]);
  const max = Math.max(...entries.map(([, v]) => v), 0);
  return (
    <ul className="space-y-1" aria-label={humanizeKey(k)}>
      {entries.map(([name, value]) => (
        <li key={name} className="grid grid-cols-[minmax(0,10rem)_1fr_3.5rem] items-center gap-2 text-xs">
          <span className="truncate text-muted" title={name}>
            {name.includes("_") || name === name.toLowerCase() ? humanizeKey(name) : name}
          </span>
          <span className="h-1.5 overflow-hidden rounded-full bg-panel-2" aria-hidden>
            <span className="block h-full rounded-full bg-accent/70" style={{ width: `${max > 0 ? (value / max) * 100 : 0}%` }} />
          </span>
          <span className="tabular text-right font-medium text-text">{formatEvidenceNumber(k, value)}</span>
        </li>
      ))}
    </ul>
  );
}

/** Array of flat objects: small table. */
function RowTable({ rows }: { rows: Record<string, Json>[] }) {
  const cols = Array.from(new Set(rows.flatMap((r) => Object.keys(r))));
  return (
    <div className="overflow-x-auto rounded border border-border">
      <table className="w-full text-xs">
        <thead className="bg-panel-2 text-left text-[11px] text-muted">
          <tr>
            {cols.map((c, i) => (
              <th key={c} scope="col" className={cn("px-2 py-1 font-medium", i > 0 && "text-right")}>
                {humanizeKey(c)}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((r, ri) => (
            <tr key={ri} className="border-t border-border">
              {cols.map((c, i) => (
                <td key={c} className={cn("px-2 py-1", i > 0 && "text-right")}>
                  <Scalar k={c} v={r[c]} />
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function EvidenceValue({ k, v }: { k: string; v: unknown }) {
  if (Array.isArray(v)) {
    if (v.length === 0) return <span className="text-subtle">None</span>;
    if (v.every((x) => isPlainObject(x))) return <RowTable rows={v as Record<string, Json>[]} />;
    return (
      <span className="flex flex-wrap gap-1">
        {v.map((x, i) => (
          <span key={i} className="rounded border border-border bg-panel-2 px-1.5 py-0.5 text-[11px] text-text">
            {String(x)}
          </span>
        ))}
      </span>
    );
  }
  if (isPlainObject(v)) {
    const values = Object.values(v);
    if (values.length === 0) return <span className="text-subtle">None</span>;
    if (values.every((x) => typeof x === "number")) {
      const nums = v as Record<string, number>;
      if (isRateKey(k) && values.every((x) => (x as number) >= 0 && (x as number) <= 1)) return <CoverageBars k={k} obj={nums} />;
      return <CountMap k={k} obj={nums} />;
    }
    return <EvidenceList evidence={v} nested />;
  }
  return <Scalar k={k} v={v} />;
}

function isBlock(v: unknown) {
  return Array.isArray(v) ? v.some((x) => isPlainObject(x)) || v.length > 3 : isPlainObject(v);
}

export function EvidenceList({
  evidence,
  nested = false,
  className,
}: {
  evidence: Record<string, unknown>;
  nested?: boolean;
  className?: string;
}) {
  const entries = Object.entries(evidence);
  const notes = entries.filter(([k, v]) => k === "note" && typeof v === "string");
  const scalars = entries.filter(([k, v]) => k !== "note" && !isBlock(v));
  const blocks = entries.filter(([k, v]) => k !== "note" && isBlock(v));
  return (
    <div className={cn("space-y-3", className)}>
      {scalars.length > 0 && (
        <dl className={cn("grid gap-x-4 gap-y-1.5 text-xs", nested ? "grid-cols-1" : "grid-cols-1 sm:grid-cols-2")}>
          {scalars.map(([k, v]) => (
            <div key={k} className="flex items-baseline justify-between gap-3 border-b border-dashed border-border pb-1">
              <dt className="min-w-0 text-muted">{humanizeKey(k)}</dt>
              <dd className="shrink-0 text-right">
                <EvidenceValue k={k} v={v} />
              </dd>
            </div>
          ))}
        </dl>
      )}
      {blocks.map(([k, v]) => (
        <div key={k}>
          <div className="mb-1.5 text-[11px] font-medium uppercase tracking-wide text-muted">{humanizeKey(k)}</div>
          <EvidenceValue k={k} v={v} />
        </div>
      ))}
      {notes.map(([k, v]) => (
        <p key={k} className="text-[11px] text-muted">
          Note: {String(v)}
        </p>
      ))}
    </div>
  );
}

/** Collapsible raw JSON so a skeptical reader can see exactly what the API returned. */
export function RawJson({ value, label = "Raw JSON" }: { value: unknown; label?: string }) {
  return (
    <details className="group text-xs">
      <summary className="cursor-pointer select-none text-muted hover:text-text">{label}</summary>
      <pre className="mt-2 max-h-72 overflow-auto rounded border border-border bg-panel-2 p-2 font-mono text-[11px] leading-relaxed text-text">
        {JSON.stringify(value, null, 2)}
      </pre>
    </details>
  );
}
