import { cn } from "@/lib/utils";

export interface HBarItem {
  key: string;
  label: React.ReactNode;
  value: number;
  display: string;
  sub?: React.ReactNode;
  muted?: boolean;
}

/** Ranked horizontal bars in plain HTML: readable labels, values in text ink, accessible as a list. */
export function HBarList({ items, max, className }: { items: HBarItem[]; max?: number; className?: string }) {
  const top = max ?? Math.max(...items.map((i) => i.value), 0);
  return (
    <ul className={cn("space-y-2.5", className)}>
      {items.map((i) => (
        <li key={i.key}>
          <div className="flex items-baseline justify-between gap-3 text-xs">
            <span className={cn("min-w-0 truncate", i.muted ? "text-subtle" : "text-text")}>{i.label}</span>
            <span className="tabular shrink-0 font-medium text-text">{i.display}</span>
          </div>
          <div className="mt-1 h-1.5 overflow-hidden rounded-full bg-panel-2">
            <div
              className={cn("h-full rounded-full", i.muted ? "bg-subtle" : "bg-accent")}
              style={{ width: `${top > 0 ? (i.value / top) * 100 : 0}%` }}
            />
          </div>
          {i.sub && <div className="mt-0.5 text-[11px] text-muted">{i.sub}</div>}
        </li>
      ))}
    </ul>
  );
}
