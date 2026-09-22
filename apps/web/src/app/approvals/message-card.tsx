"use client";

import { Pencil } from "lucide-react";
import { useRouter } from "next/navigation";
import { useId, useState, useTransition } from "react";

import { Button } from "@/components/ui/button";
import { clientApi } from "@/lib/client-api";

import type { DraftStatus } from "./types";

/**
 * Shows the drafted message and lets a reviewer edit it in place. Saving calls PUT /drafts/{id},
 * which re-runs every guardrail server-side; approved drafts drop back to review.
 */
export function MessageCard({
  draftId,
  channel,
  subject,
  body,
  status,
}: {
  draftId: string;
  channel: "email" | "linkedin" | "call_prep";
  subject: string | null;
  body: string;
  status: DraftStatus;
}) {
  const router = useRouter();
  const formId = useId();
  const [editing, setEditing] = useState(false);
  const [draftSubject, setDraftSubject] = useState(subject ?? "");
  const [draftBody, setDraftBody] = useState(body);
  const [saving, setSaving] = useState(false);
  const [pending, startTransition] = useTransition();
  const [error, setError] = useState<string | null>(null);

  const locked = status === "ready";
  const hasSubject = channel === "email";
  const dirty = draftBody !== body || (hasSubject && draftSubject !== (subject ?? ""));

  function startEdit() {
    setDraftSubject(subject ?? "");
    setDraftBody(body);
    setError(null);
    setEditing(true);
  }

  async function save(e: React.FormEvent) {
    e.preventDefault();
    if (!draftBody.trim()) {
      setError("The message body cannot be empty.");
      return;
    }
    setSaving(true);
    setError(null);
    try {
      await clientApi(`/drafts/${draftId}`, {
        method: "PUT",
        body: { subject: hasSubject ? draftSubject.trim() || null : subject, body: draftBody },
      });
      setEditing(false);
      startTransition(() => router.refresh());
    } catch (err) {
      setError(err instanceof Error ? err.message : "Saving failed");
    } finally {
      setSaving(false);
    }
  }

  const busy = saving || pending;

  if (!editing) {
    return (
      <div>
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            {hasSubject && (
              <>
                <div className="text-[11px] font-medium uppercase tracking-wide text-muted">Subject</div>
                <div className="mt-0.5 text-sm font-medium text-text">{subject || <span className="text-subtle">No subject</span>}</div>
              </>
            )}
          </div>
          <div className="flex shrink-0 flex-col items-end gap-1">
            <Button type="button" size="sm" variant="secondary" onClick={startEdit} disabled={locked || busy}>
              <Pencil className="size-3.5" aria-hidden /> {busy ? "Refreshing…" : "Edit"}
            </Button>
            {locked && <span className="text-[11px] text-muted">Move back to draft to edit</span>}
          </div>
        </div>
        <div className="mt-3 whitespace-pre-wrap break-words rounded-md border border-border bg-panel-2 px-3 py-2.5 text-[13px] leading-relaxed text-text">
          {body}
        </div>
      </div>
    );
  }

  return (
    <form onSubmit={save} className="space-y-3" aria-label="Edit draft">
      {status === "approved" && (
        <p className="rounded-md bg-warning-soft px-3 py-2 text-xs text-warning">
          This draft is approved. Saving an edit sends it back to review so the new wording is approved explicitly.
        </p>
      )}
      {hasSubject && (
        <div className="flex flex-col gap-1">
          <label htmlFor={`${formId}-subject`} className="text-[11px] font-medium text-muted">
            Subject
          </label>
          <input
            id={`${formId}-subject`}
            value={draftSubject}
            onChange={(e) => setDraftSubject(e.target.value)}
            maxLength={500}
            className="h-8 rounded-md border border-border bg-panel px-2 text-sm text-text hover:border-border-strong"
          />
        </div>
      )}
      <div className="flex flex-col gap-1">
        <label htmlFor={`${formId}-body`} className="text-[11px] font-medium text-muted">
          {channel === "call_prep" ? "Call prep notes" : "Message"}
        </label>
        <textarea
          id={`${formId}-body`}
          value={draftBody}
          onChange={(e) => setDraftBody(e.target.value)}
          maxLength={5000}
          rows={Math.min(18, Math.max(8, draftBody.split("\n").length + 1))}
          className="rounded-md border border-border bg-panel px-3 py-2 text-[13px] leading-relaxed text-text hover:border-border-strong"
        />
        <span className="tabular text-right text-[11px] text-muted">{draftBody.length} / 5000</span>
      </div>
      <p className="text-[11px] text-muted">
        Guardrails re-run on save. Numbers must still appear in cited evidence, and blocking failures will prevent approval.
      </p>
      {error && (
        <p role="alert" className="text-xs text-danger">
          {error}
        </p>
      )}
      <div className="flex items-center gap-2">
        <Button type="submit" size="sm" variant="primary" disabled={busy || !dirty}>
          {busy ? "Saving…" : "Save and re-check"}
        </Button>
        <Button type="button" size="sm" variant="ghost" onClick={() => setEditing(false)} disabled={busy}>
          Cancel
        </Button>
      </div>
    </form>
  );
}
