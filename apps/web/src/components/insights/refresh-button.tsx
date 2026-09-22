"use client";

import { RefreshCw } from "lucide-react";
import { useRouter } from "next/navigation";
import { useTransition } from "react";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

/** Re-renders the current server page (re-running its live queries) without a full reload. */
export function RefreshButton({ children, pendingLabel = "Running…" }: { children: React.ReactNode; pendingLabel?: string }) {
  const router = useRouter();
  const [pending, startTransition] = useTransition();
  return (
    <Button
      type="button"
      size="sm"
      variant="secondary"
      onClick={() => startTransition(() => router.refresh())}
      disabled={pending}
      aria-busy={pending}
    >
      <RefreshCw className={cn("size-3.5", pending && "animate-spin")} aria-hidden />
      {pending ? pendingLabel : children}
    </Button>
  );
}
