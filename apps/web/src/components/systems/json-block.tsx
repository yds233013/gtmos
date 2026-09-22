import { ChevronRight } from "lucide-react";

import { cn } from "@/lib/utils";

/** Pretty-printed JSON inside a native <details>: collapsible and keyboard accessible without client JS. */
export function JsonBlock({
  value,
  summary = "Raw JSON",
  open = false,
  className,
}: {
  value: unknown;
  summary?: React.ReactNode;
  open?: boolean;
  className?: string;
}) {
  return (
    <details open={open} className={cn("group rounded-md border border-border", className)}>
      <summary className="flex cursor-pointer list-none items-center gap-1.5 px-3 py-2 text-xs font-medium text-muted hover:text-text [&::-webkit-details-marker]:hidden">
        <ChevronRight className="size-3.5 transition-transform group-open:rotate-90" aria-hidden />
        {summary}
      </summary>
      <pre className="max-h-96 overflow-auto border-t border-border bg-panel-2 px-3 py-2 font-mono text-[11px] leading-5 text-text">
        {JSON.stringify(value, null, 2)}
      </pre>
    </details>
  );
}

/** Flat key/value rendering of a step output or details object; nested values fall back to compact JSON. */
export function KeyValues({ data, className }: { data: Record<string, unknown> | null | undefined; className?: string }) {
  const entries = Object.entries(data ?? {});
  if (!entries.length) return <p className="text-[11px] text-subtle">No output.</p>;
  return (
    <dl className={cn("grid grid-cols-[minmax(0,auto)_minmax(0,1fr)] gap-x-3 gap-y-1 text-[11px]", className)}>
      {entries.map(([k, v]) => (
        <div key={k} className="contents">
          <dt className="truncate text-muted">{k}</dt>
          <dd className="min-w-0 break-words font-mono text-text">{formatValue(v)}</dd>
        </div>
      ))}
    </dl>
  );
}

function formatValue(v: unknown): string {
  if (v === null || v === undefined) return "—";
  if (Array.isArray(v)) return v.length ? v.map((x) => (typeof x === "object" ? JSON.stringify(x) : String(x))).join(", ") : "[]";
  if (typeof v === "object") return JSON.stringify(v);
  return String(v);
}
