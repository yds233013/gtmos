"use client";

import { useRouter } from "next/navigation";
import { useState, useTransition } from "react";

import { clientApi } from "@/lib/client-api";

import { Button } from "./button";

/**
 * Calls an API mutation, then refreshes server components so the page shows the new state.
 * Errors render inline (no browser dialogs).
 */
export function ActionButton({
  path,
  method = "POST",
  body,
  children,
  variant = "secondary",
  size = "sm",
  onDone,
  confirmLabel,
  className,
  disabled,
}: {
  path: string;
  method?: "POST" | "PUT" | "PATCH" | "DELETE";
  body?: unknown;
  children: React.ReactNode;
  variant?: "primary" | "secondary" | "ghost" | "danger";
  size?: "sm" | "md";
  onDone?: (result: unknown) => void;
  /** When set, the first click arms the button and a second click confirms (no modal dialog). */
  confirmLabel?: string;
  className?: string;
  disabled?: boolean;
}) {
  const router = useRouter();
  const [pending, startTransition] = useTransition();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [armed, setArmed] = useState(false);

  async function run() {
    if (confirmLabel && !armed) {
      setArmed(true);
      return;
    }
    setArmed(false);
    setBusy(true);
    setError(null);
    try {
      const result = await clientApi(path, { method, body: body ?? {} });
      onDone?.(result);
      startTransition(() => router.refresh());
    } catch (e) {
      setError(e instanceof Error ? e.message : "Request failed");
    } finally {
      setBusy(false);
    }
  }

  const loading = busy || pending;
  return (
    <span className="inline-flex flex-col items-start gap-1">
      <Button
        type="button"
        variant={armed ? "danger" : variant}
        size={size}
        onClick={run}
        disabled={disabled || loading}
        aria-busy={loading}
        className={className}
      >
        {loading ? "Working…" : armed ? confirmLabel : children}
      </Button>
      {error && (
        <span role="alert" className="max-w-xs text-[11px] text-danger">
          {error}
        </span>
      )}
    </span>
  );
}
