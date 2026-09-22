"use client";

import { useRouter } from "next/navigation";
import { useId, useState, useTransition } from "react";

import { Button } from "@/components/ui/button";
import { clientApi } from "@/lib/client-api";

import type { DraftStatus } from "./types";

/** A transition that asks for a reason first (reject, send back). The reason lands in the audit log. */
export function ReasonTransition({
  draftId,
  target,
  label,
  confirmLabel,
  placeholder,
  variant = "secondary",
}: {
  draftId: string;
  target: DraftStatus;
  label: string;
  confirmLabel: string;
  placeholder: string;
  variant?: "secondary" | "danger" | "ghost";
}) {
  const router = useRouter();
  const id = useId();
  const [open, setOpen] = useState(false);
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [pending, startTransition] = useTransition();
  const [error, setError] = useState<string | null>(null);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await clientApi(`/drafts/${draftId}/transition`, {
        method: "POST",
        body: { target, reason: reason.trim() || null },
      });
      setOpen(false);
      setReason("");
      startTransition(() => router.refresh());
    } catch (err) {
      setError(err instanceof Error ? err.message : "Request failed");
    } finally {
      setBusy(false);
    }
  }

  const loading = busy || pending;

  if (!open) {
    return (
      <Button type="button" size="sm" variant={variant} onClick={() => setOpen(true)} disabled={loading} aria-expanded={false}>
        {loading ? "Working…" : label}
      </Button>
    );
  }

  return (
    <form onSubmit={submit} className="w-full space-y-2 rounded-md border border-border bg-panel-2 p-3">
      <label htmlFor={id} className="block text-[11px] font-medium text-muted">
        Reason <span className="font-normal">(optional, recorded in the audit log)</span>
      </label>
      <textarea
        id={id}
        value={reason}
        onChange={(e) => setReason(e.target.value)}
        maxLength={1000}
        rows={2}
        placeholder={placeholder}
        autoFocus
        className="w-full rounded-md border border-border bg-panel px-2 py-1.5 text-xs text-text placeholder:text-subtle"
      />
      {error && (
        <p role="alert" className="text-[11px] text-danger">
          {error}
        </p>
      )}
      <div className="flex items-center gap-2">
        <Button type="submit" size="sm" variant={variant === "danger" ? "danger" : "primary"} disabled={loading}>
          {loading ? "Working…" : confirmLabel}
        </Button>
        <Button type="button" size="sm" variant="ghost" onClick={() => setOpen(false)} disabled={loading}>
          Cancel
        </Button>
      </div>
    </form>
  );
}
