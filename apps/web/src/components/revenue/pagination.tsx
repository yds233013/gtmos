import { ChevronLeft, ChevronRight } from "lucide-react";
import Link from "next/link";

import { num } from "@/lib/format";
import { cn } from "@/lib/utils";

import { hrefWith } from "./query";

/** Server-rendered pager: plain links, so it works without client JS and keeps the URL shareable. */
export function Pagination({
  base,
  params,
  page,
  pageSize,
  total,
  noun = "rows",
}: {
  base: string;
  params: Record<string, string | undefined>;
  page: number;
  pageSize: number;
  total: number;
  noun?: string;
}) {
  const pages = Math.max(1, Math.ceil(total / pageSize));
  const from = total === 0 ? 0 : (page - 1) * pageSize + 1;
  const to = Math.min(total, page * pageSize);
  const linkCls =
    "inline-flex h-7 items-center gap-1 rounded-md border border-border bg-panel px-2 text-xs font-medium text-text hover:bg-panel-2";
  const disabledCls = "pointer-events-none opacity-40";
  return (
    <nav
      aria-label="Pagination"
      className="flex flex-wrap items-center justify-between gap-2 border-t border-border px-4 py-2.5 text-xs text-muted"
    >
      <span className="tabular">
        {num(from)}–{num(to)} of {num(total)} {noun}
      </span>
      <div className="flex items-center gap-2">
        <span className="tabular hidden sm:inline">
          Page {num(page)} of {num(pages)}
        </span>
        <Link
          href={hrefWith(base, params, { page: page > 2 ? page - 1 : null })}
          aria-disabled={page <= 1}
          tabIndex={page <= 1 ? -1 : undefined}
          className={cn(linkCls, page <= 1 && disabledCls)}
        >
          <ChevronLeft className="size-3.5" aria-hidden /> Prev
        </Link>
        <Link
          href={hrefWith(base, params, { page: Math.min(pages, page + 1) })}
          aria-disabled={page >= pages}
          tabIndex={page >= pages ? -1 : undefined}
          className={cn(linkCls, page >= pages && disabledCls)}
        >
          Next <ChevronRight className="size-3.5" aria-hidden />
        </Link>
      </div>
    </nav>
  );
}
