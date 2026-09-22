import { cn } from "@/lib/utils";

/** Horizontal meter: points out of max. */
export function ScoreBar({
  value,
  max,
  className,
  tone = "accent",
}: {
  value: number;
  max: number;
  className?: string;
  tone?: "accent" | "success" | "warning" | "danger" | "muted";
}) {
  const pct = max > 0 ? Math.max(0, Math.min(1, value / max)) : 0;
  const color = {
    accent: "bg-accent",
    success: "bg-success",
    warning: "bg-warning",
    danger: "bg-danger",
    muted: "bg-subtle",
  }[tone];
  return (
    <div
      role="meter"
      aria-valuemin={0}
      aria-valuemax={max}
      aria-valuenow={value}
      className={cn("h-1.5 w-full overflow-hidden rounded-full bg-panel-2", className)}
    >
      <div className={cn("h-full rounded-full", color)} style={{ width: `${pct * 100}%` }} />
    </div>
  );
}

const DEFAULT_MAX: Record<string, number> = { fit: 35, intent: 25, timing: 15, technical: 15, engagement: 10 };

/** Compact 5-segment breakdown used in tables. Segment widths follow the active ICP's category weights. */
export function CategoryStrip({
  categories,
  max = DEFAULT_MAX,
}: {
  categories: Record<string, number> | null;
  max?: Record<string, number>;
}) {
  if (!categories) return <span className="text-xs text-subtle">—</span>;
  const CATEGORY_MAX = { ...DEFAULT_MAX, ...max };
  return (
    <div className="flex w-36 gap-0.5" aria-label="Score breakdown">
      {Object.entries(CATEGORY_MAX).map(([k, max]) => (
        <div key={k} className="flex-1" title={`${k}: ${categories[k]?.toFixed(1)} / ${max}`} style={{ flexGrow: max }}>
          <ScoreBar value={categories[k] ?? 0} max={max} className="h-1" />
        </div>
      ))}
    </div>
  );
}
