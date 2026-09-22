"use client";

import { Menu, X } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useState } from "react";

import { cn } from "@/lib/utils";

import { NAV } from "./nav";

function isActive(pathname: string, href: string): boolean {
  return href === "/" ? pathname === "/" : pathname === href || pathname.startsWith(`${href}/`);
}

function NavLinks({ onNavigate }: { onNavigate?: () => void }) {
  const pathname = usePathname();
  return (
    <nav aria-label="Main" className="space-y-5">
      {NAV.map((group) => (
        <div key={group.section}>
          <div className="px-2 pb-1 text-[11px] font-medium uppercase tracking-wide text-subtle">{group.section}</div>
          <ul className="space-y-0.5">
            {group.items.map(({ href, label, icon: Icon }) => {
              const active = isActive(pathname, href);
              return (
                <li key={href}>
                  <Link
                    href={href}
                    onClick={onNavigate}
                    aria-current={active ? "page" : undefined}
                    className={cn(
                      "flex items-center gap-2 rounded-md px-2 py-1.5 text-sm transition-colors",
                      active ? "bg-panel-2 font-medium text-text" : "text-muted hover:bg-panel-2 hover:text-text",
                    )}
                  >
                    <Icon className="size-4 shrink-0" aria-hidden />
                    {label}
                  </Link>
                </li>
              );
            })}
          </ul>
        </div>
      ))}
    </nav>
  );
}

function Brand() {
  return (
    <Link href="/" className="flex items-center gap-2 px-2">
      <span className="grid size-6 place-items-center rounded bg-text text-[11px] font-bold text-bg">G</span>
      <span className="text-sm font-semibold tracking-tight">GTMOS</span>
    </Link>
  );
}

export function Sidebar({ workspaceName }: { workspaceName: string }) {
  const [open, setOpen] = useState(false);
  return (
    <>
      <aside className="sticky top-0 hidden h-screen w-56 shrink-0 flex-col border-r border-border bg-panel px-3 py-4 lg:flex">
        <Brand />
        <div className="mt-1 truncate px-2 text-xs text-muted" title={workspaceName}>
          {workspaceName}
        </div>
        <div className="mt-6 flex-1 overflow-y-auto">
          <NavLinks />
        </div>
      </aside>
      <div className="sticky top-0 z-30 flex items-center justify-between border-b border-border bg-panel px-4 py-2 lg:hidden">
        <Brand />
        <button
          type="button"
          aria-label={open ? "Close navigation" : "Open navigation"}
          aria-expanded={open}
          onClick={() => setOpen((o) => !o)}
          className="rounded-md p-1.5 text-muted hover:bg-panel-2"
        >
          {open ? <X className="size-5" /> : <Menu className="size-5" />}
        </button>
      </div>
      {open && (
        <div className="fixed inset-0 z-20 bg-bg/95 px-4 pb-6 pt-16 lg:hidden">
          <NavLinks onNavigate={() => setOpen(false)} />
        </div>
      )}
    </>
  );
}
