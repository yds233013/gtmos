import Link from "next/link";

import { num } from "@/lib/format";
import { cn } from "@/lib/utils";

export interface FilterTab {
  key: string;
  label: string;
  href: string;
  count?: number | null;
}

/** URL-driven tabs (searchParams), so filtered views are linkable and work without client JS. */
export function FilterTabs({ tabs, active, label, className }: { tabs: FilterTab[]; active: string; label: string; className?: string }) {
  return (
    <nav aria-label={label} className={cn("flex gap-1 overflow-x-auto border-b border-border", className)}>
      {tabs.map((t) => {
        const on = t.key === active;
        return (
          <Link
            key={t.key}
            href={t.href}
            scroll={false}
            aria-current={on ? "page" : undefined}
            className={cn(
              "-mb-px inline-flex items-center gap-1.5 whitespace-nowrap border-b-2 px-3 py-2 text-xs transition-colors",
              on ? "border-accent font-medium text-text" : "border-transparent text-muted hover:text-text",
            )}
          >
            {t.label}
            {t.count !== undefined && t.count !== null && (
              <span className={cn("tabular rounded px-1 text-[10px]", on ? "bg-accent-soft text-accent-text" : "bg-panel-2 text-muted")}>
                {num(t.count)}
              </span>
            )}
          </Link>
        );
      })}
    </nav>
  );
}
