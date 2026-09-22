"use client";

import { ArrowUp, ChevronRight, CircleAlert, Loader2, TriangleAlert } from "lucide-react";
import { useId, useRef, useState } from "react";

import { RawJson } from "@/components/insights/evidence";
import { MiniMarkdown, renderInline } from "@/components/insights/mini-markdown";
import type { CopilotAnswer } from "@/components/insights/types";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { clientApi } from "@/lib/client-api";
import { titleCase } from "@/lib/format";
import { cn } from "@/lib/utils";

type Turn =
  | { id: number; question: string; state: "pending" }
  | { id: number; question: string; state: "done"; result: CopilotAnswer }
  | { id: number; question: string; state: "error"; error: string };

const LOW_CONFIDENCE = 0.5;

function formatParams(params: Record<string, unknown>): string {
  const entries = Object.entries(params ?? {});
  if (!entries.length) return "default parameters";
  return entries.map(([k, v]) => `${k}=${typeof v === "string" ? v : JSON.stringify(v)}`).join(", ");
}

function Chip({ children, onClick, disabled }: { children: React.ReactNode; onClick: () => void; disabled?: boolean }) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      className="rounded-full border border-border bg-panel px-2.5 py-1 text-left text-xs text-text transition-colors hover:border-border-strong hover:bg-panel-2 disabled:opacity-50"
    >
      {children}
    </button>
  );
}

function HowComputed({ result }: { result: CopilotAnswer }) {
  return (
    <details className="group border-t border-border">
      <summary className="flex cursor-pointer select-none items-center gap-1.5 px-4 py-2.5 text-xs font-medium text-muted hover:text-text">
        <ChevronRight className="size-3.5 transition-transform group-open:rotate-90" aria-hidden />
        How this was computed
      </summary>
      <div className="grid gap-4 px-4 pb-4 text-xs md:grid-cols-2">
        <div>
          <h4 className="mb-1.5 text-[11px] font-semibold uppercase tracking-wide text-muted">Plan</h4>
          <ol className="list-decimal space-y-1 pl-4 text-text marker:text-muted">
            {result.plan.map((step, i) => (
              <li key={i}>{renderInline(step)}</li>
            ))}
          </ol>
        </div>
        <div>
          <h4 className="mb-1.5 text-[11px] font-semibold uppercase tracking-wide text-muted">Approved metric calls</h4>
          {result.queries.length ? (
            <ul className="space-y-1">
              {result.queries.map((q, i) => (
                <li key={i} className="rounded border border-border bg-panel-2 px-2 py-1 font-mono text-[11px] text-text">
                  {q.metric}
                  <span className="text-muted">({formatParams(q.params)})</span>
                </li>
              ))}
            </ul>
          ) : (
            <p className="text-muted">No metric was called.</p>
          )}
          <dl className="mt-3 grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-[11px]">
            <dt className="text-muted">Intent</dt>
            <dd className="font-mono text-text">{result.intent}</dd>
            <dt className="text-muted">Confidence</dt>
            <dd className="tabular text-text">{result.confidence.toFixed(2)}</dd>
            <dt className="text-muted">Generator</dt>
            <dd className="text-text">{result.generator}</dd>
          </dl>
        </div>
        <div className="md:col-span-2">
          <h4 className="mb-1.5 text-[11px] font-semibold uppercase tracking-wide text-muted">Guardrails</h4>
          <ul className="space-y-1">
            {result.guardrails.map((g) => (
              <li key={g} className="flex items-start gap-1.5 text-text">
                <span aria-hidden className="mt-1.5 size-1 shrink-0 rounded-full bg-success" />
                {g}
              </li>
            ))}
          </ul>
        </div>
        <div className="md:col-span-2">
          <RawJson value={result.data} label="Computed data returned by the metrics" />
        </div>
      </div>
    </details>
  );
}

function TurnCard({ turn, onAsk, busy }: { turn: Turn; onAsk: (q: string) => void; busy: boolean }) {
  return (
    <article className="overflow-hidden rounded-lg border border-border bg-panel" aria-busy={turn.state === "pending"}>
      <header className="flex items-start justify-between gap-3 border-b border-border bg-panel-2/50 px-4 py-2.5">
        <p className="text-sm font-medium text-text">{turn.question}</p>
        {turn.state === "done" && (
          <Badge tone="neutral" title="The approved metric family this question was routed to">
            {titleCase(turn.result.intent)}
          </Badge>
        )}
      </header>

      {turn.state === "pending" && (
        <div className="flex items-center gap-2 px-4 py-4 text-xs text-muted" role="status">
          <Loader2 className="size-3.5 animate-spin" aria-hidden />
          Routing to approved metrics…
        </div>
      )}

      {turn.state === "error" && (
        <div role="alert" className="flex items-start gap-2 px-4 py-4 text-xs text-danger">
          <CircleAlert className="mt-0.5 size-3.5 shrink-0" aria-hidden />
          {turn.error}
        </div>
      )}

      {turn.state === "done" && (
        <>
          <div className="space-y-3 px-4 py-4">
            {turn.result.confidence < LOW_CONFIDENCE && (
              <div className="flex items-start gap-2 rounded-md border border-warning/30 bg-warning-soft px-3 py-2 text-xs">
                <TriangleAlert className="mt-0.5 size-3.5 shrink-0 text-warning" aria-hidden />
                <span className="text-text">
                  Low-confidence match ({turn.result.confidence.toFixed(2)}). The question didn&apos;t map cleanly to an approved metric, so
                  this is the closest one ({titleCase(turn.result.intent)}). Try rephrasing or pick a suggested question.
                </span>
              </div>
            )}
            <MiniMarkdown source={turn.result.answer} />
          </div>
          <HowComputed result={turn.result} />
          {turn.result.suggested.length > 0 && (
            <div className="flex flex-wrap items-center gap-1.5 border-t border-border px-4 py-2.5">
              <span className="mr-1 text-[11px] text-muted">Follow up</span>
              {turn.result.suggested
                .filter((s) => s !== turn.question)
                .slice(0, 3)
                .map((s) => (
                  <Chip key={s} onClick={() => onAsk(s)} disabled={busy}>
                    {s}
                  </Chip>
                ))}
            </div>
          )}
        </>
      )}
    </article>
  );
}

export function CopilotChat({ suggestions, suggestionsFailed }: { suggestions: string[]; suggestionsFailed: boolean }) {
  const [turns, setTurns] = useState<Turn[]>([]);
  const [question, setQuestion] = useState("");
  const [inputError, setInputError] = useState<string | null>(null);
  const nextId = useRef(1);
  const inputId = useId();
  const busy = turns.some((t) => t.state === "pending");

  async function ask(raw: string) {
    const q = raw.trim();
    if (q.length < 3) {
      setInputError("Ask a question of at least 3 characters.");
      return;
    }
    if (q.length > 500) {
      setInputError("Keep questions under 500 characters.");
      return;
    }
    setInputError(null);
    setQuestion("");
    const id = nextId.current++;
    setTurns((prev) => [{ id, question: q, state: "pending" }, ...prev]);
    try {
      const result = await clientApi<CopilotAnswer>("/copilot/ask", { method: "POST", body: { question: q } });
      setTurns((prev) => prev.map((t) => (t.id === id ? { id, question: q, state: "done", result } : t)));
    } catch (e) {
      const error = e instanceof Error ? e.message : "The Copilot request failed.";
      setTurns((prev) => prev.map((t) => (t.id === id ? { id, question: q, state: "error", error } : t)));
    }
  }

  return (
    <div className="space-y-4">
      <form
        className="rounded-lg border border-border bg-panel p-3"
        onSubmit={(e) => {
          e.preventDefault();
          void ask(question);
        }}
      >
        <label htmlFor={inputId} className="sr-only">
          Ask the GTM Copilot a question
        </label>
        <div className="flex items-center gap-2">
          <input
            id={inputId}
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
            placeholder="e.g. Why did pipeline fall this month?"
            maxLength={500}
            autoComplete="off"
            aria-invalid={inputError ? true : undefined}
            aria-describedby={inputError ? `${inputId}-err` : undefined}
            className="h-9 min-w-0 flex-1 rounded-md border border-border bg-bg px-3 text-sm text-text placeholder:text-subtle focus:border-accent focus:outline-none"
          />
          <Button type="submit" variant="primary" disabled={busy || !question.trim()} aria-busy={busy}>
            {busy ? <Loader2 className="size-3.5 animate-spin" aria-hidden /> : <ArrowUp className="size-3.5" aria-hidden />}
            Ask
          </Button>
        </div>
        {inputError && (
          <p id={`${inputId}-err`} role="alert" className="mt-1.5 text-[11px] text-danger">
            {inputError}
          </p>
        )}
        <div className="mt-3">
          <div className="mb-1.5 text-[11px] font-medium text-muted">Suggested questions</div>
          {suggestions.length ? (
            <div className="flex flex-wrap gap-1.5">
              {suggestions.map((s) => (
                <Chip key={s} onClick={() => void ask(s)} disabled={busy}>
                  {s}
                </Chip>
              ))}
            </div>
          ) : (
            <p className="text-xs text-muted">
              {suggestionsFailed ? "Suggestions are unavailable right now; you can still type a question." : "No suggestions."}
            </p>
          )}
        </div>
      </form>

      <section aria-label="Answers" aria-live="polite" className="space-y-3">
        {turns.length === 0 ? (
          <div className={cn("rounded-lg border border-dashed border-border px-6 py-10 text-center")}>
            <p className="text-sm font-medium text-text">No questions yet</p>
            <p className="mx-auto mt-1 max-w-md text-xs text-muted">
              Pick a suggested question or type your own. Each answer shows the plan, the approved metric calls and the guardrails that
              produced it.
            </p>
          </div>
        ) : (
          turns.map((t) => <TurnCard key={t.id} turn={t} onAsk={(q) => void ask(q)} busy={busy} />)
        )}
      </section>
    </div>
  );
}
