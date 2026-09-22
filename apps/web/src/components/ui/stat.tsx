import { cn } from "@/lib/utils";

export function Stat({
  label,
  value,
  sub,
  hint,
  className,
}: {
  label: string;
  value: React.ReactNode;
  sub?: React.ReactNode;
  hint?: string;
  className?: string;
}) {
  return (
    <div className={cn("min-w-0", className)} title={hint}>
      <div className="truncate text-xs text-muted">{label}</div>
      <div className="tabular mt-1 text-xl font-semibold tracking-tight text-text">{value}</div>
      {sub && <div className="mt-0.5 truncate text-xs text-muted">{sub}</div>}
    </div>
  );
}

export function StatGrid({ children, className }: { children: React.ReactNode; className?: string }) {
  return (
    <div
      className={cn(
        "grid grid-cols-2 gap-px overflow-hidden rounded-lg border border-border bg-border sm:grid-cols-3 lg:grid-cols-6",
        className,
      )}
    >
      {children}
    </div>
  );
}

export function StatCell(props: React.ComponentProps<typeof Stat>) {
  return <Stat {...props} className={cn("bg-panel px-4 py-3", props.className)} />;
}
