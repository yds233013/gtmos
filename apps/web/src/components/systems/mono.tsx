import { cn } from "@/lib/utils";

/** Correlation ids, idempotency keys and other machine identifiers. */
export function Mono({ children, className, title }: { children: React.ReactNode; className?: string; title?: string }) {
  return (
    <code title={title} className={cn("break-all font-mono text-[11px] text-muted", className)}>
      {children}
    </code>
  );
}
