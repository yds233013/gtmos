import Link from "next/link";

import { cn } from "@/lib/utils";

/** Filter pill that navigates via searchParams (server-rendered, no client state). */
export function ChipLink({
  href,
  active,
  children,
  scroll = false,
}: {
  href: string;
  active?: boolean;
  children: React.ReactNode;
  scroll?: boolean;
}) {
  return (
    <Link
      href={href}
      scroll={scroll}
      aria-current={active ? "page" : undefined}
      className={cn(
        "inline-flex items-center rounded-full border px-2.5 py-1 text-xs transition-colors",
        active
          ? "border-accent/40 bg-accent-soft font-medium text-accent-text"
          : "border-border bg-panel text-muted hover:bg-panel-2 hover:text-text",
      )}
    >
      {children}
    </Link>
  );
}
