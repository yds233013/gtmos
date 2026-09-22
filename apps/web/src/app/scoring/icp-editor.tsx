"use client";

import { ArrowDown, ArrowUp, Loader2, Plus, RotateCcw, TriangleAlert, X } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useId, useMemo, useState, useTransition } from "react";

import type { ICPDefinition, ICPPreview, SignalType, Weights } from "@/components/insights/types";
import { GradeBadge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Panel } from "@/components/ui/panel";
import { DEMO_ACTOR } from "@/lib/client-api";
import { num } from "@/lib/format";
import type { Grade } from "@/lib/types";
import { cn } from "@/lib/utils";

const CATS: (keyof Weights)[] = ["fit", "intent", "timing", "technical", "engagement"];
const GRADES: Grade[] = ["A", "B", "C", "D", "X"];
const SIZE_FIELDS: { key: keyof ICPDefinition["size"]; label: string }[] = [
  { key: "hard_min_employees", label: "Exclude below" },
  { key: "min_employees", label: "Min" },
  { key: "sweet_spot_min", label: "Sweet spot from" },
  { key: "sweet_spot_max", label: "Sweet spot to" },
  { key: "max_employees", label: "Max" },
];

interface FieldError {
  loc: string[];
  msg: string;
}

class ApiFailure extends Error {
  constructor(
    message: string,
    public status: number,
    public details: FieldError[],
  ) {
    super(message);
  }
}

/** Like clientApi, but keeps FastAPI's per-field 422 details so they can render next to the inputs. */
async function send<T>(path: string, method: "POST" | "PUT", body: unknown): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`/api/v1${path}`, {
      method,
      headers: { "Content-Type": "application/json", "X-GTMOS-Actor": DEMO_ACTOR },
      body: JSON.stringify(body),
    });
  } catch {
    throw new ApiFailure("The GTMOS API is not reachable.", 0, []);
  }
  const text = await res.text();
  let data: unknown = null;
  try {
    data = text ? JSON.parse(text) : null;
  } catch {
    data = null;
  }
  if (!res.ok) {
    const obj = (data ?? {}) as { error?: unknown; detail?: unknown; details?: FieldError[] };
    const details = Array.isArray(obj.details) ? obj.details : Array.isArray(obj.detail) ? (obj.detail as FieldError[]) : [];
    const message = typeof obj.error === "string" ? obj.error : typeof obj.detail === "string" ? obj.detail : res.statusText;
    throw new ApiFailure(message || `Request failed (${res.status})`, res.status, details);
  }
  return data as T;
}

/** Map a pydantic loc (["body","weights"], ["body","size"], …) to one of our editor sections. */
function sectionFor(loc: string[]): "weights" | "size" | "core_industries" | "positive_signals" | "other" {
  const path = loc.filter((p) => p !== "body");
  const head = path[0];
  if (head === "weights" || head === "size" || head === "core_industries" || head === "positive_signals") return head;
  return "other";
}

function cleanMsg(msg: string) {
  return msg.replace(/^Value error, /, "");
}

function NumberField({
  label,
  value,
  onChange,
  min = 0,
  step = 1,
  invalid,
  suffix,
}: {
  label: string;
  value: number;
  onChange: (v: number) => void;
  min?: number;
  step?: number;
  invalid?: boolean;
  suffix?: string;
}) {
  const id = useId();
  return (
    <div className="min-w-0">
      <label htmlFor={id} className="block truncate text-[11px] text-muted">
        {label}
      </label>
      <div className="mt-0.5 flex items-center gap-1">
        <input
          id={id}
          type="number"
          inputMode="decimal"
          min={min}
          step={step}
          value={Number.isFinite(value) ? value : ""}
          onChange={(e) => onChange(e.target.value === "" ? NaN : Number(e.target.value))}
          aria-invalid={invalid || undefined}
          className={cn(
            "tabular h-8 w-full min-w-0 rounded-md border bg-bg px-2 text-sm text-text focus:border-accent focus:outline-none",
            invalid ? "border-danger" : "border-border",
          )}
        />
        {suffix && <span className="shrink-0 text-[11px] text-muted">{suffix}</span>}
      </div>
    </div>
  );
}

function FieldErrors({ errors }: { errors: FieldError[] }) {
  if (!errors.length) return null;
  return (
    <ul role="alert" className="mt-2 space-y-0.5 text-[11px] text-danger">
      {errors.map((e, i) => (
        <li key={i}>{cleanMsg(e.msg)}</li>
      ))}
    </ul>
  );
}

function IndustryEditor({
  value,
  onChange,
  suggestions,
  invalid,
}: {
  value: string[];
  onChange: (v: string[]) => void;
  suggestions: string[];
  invalid: boolean;
}) {
  const [draft, setDraft] = useState("");
  const id = useId();
  const add = (name: string) => {
    const n = name.trim();
    if (n && !value.includes(n)) onChange([...value, n]);
    setDraft("");
  };
  const remaining = suggestions.filter((s) => !value.includes(s));
  return (
    <div>
      <div className={cn("flex flex-wrap gap-1 rounded-md border bg-bg p-1.5", invalid ? "border-danger" : "border-border")}>
        {value.map((ind) => (
          <span key={ind} className="inline-flex items-center gap-1 rounded bg-accent-soft py-0.5 pl-1.5 pr-0.5 text-[11px] text-accent-text">
            {ind}
            <button
              type="button"
              onClick={() => onChange(value.filter((v) => v !== ind))}
              className="rounded p-0.5 hover:bg-accent/15"
              aria-label={`Remove ${ind}`}
            >
              <X className="size-3" aria-hidden />
            </button>
          </span>
        ))}
        <label htmlFor={id} className="sr-only">
          Add a core industry
        </label>
        <input
          id={id}
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") {
              e.preventDefault();
              add(draft);
            }
          }}
          placeholder={value.length ? "Add industry…" : "Type an industry and press Enter"}
          className="h-6 min-w-32 flex-1 bg-transparent px-1 text-xs text-text placeholder:text-subtle focus:outline-none"
        />
      </div>
      {remaining.length > 0 && (
        <div className="mt-1.5 flex flex-wrap items-center gap-1">
          <span className="mr-1 text-[11px] text-muted">Promote:</span>
          {remaining.map((s) => (
            <button
              key={s}
              type="button"
              onClick={() => add(s)}
              className="inline-flex items-center gap-0.5 rounded border border-border px-1.5 py-0.5 text-[11px] text-muted hover:bg-panel-2 hover:text-text"
            >
              <Plus className="size-3" aria-hidden />
              {s}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

function DistributionTable({ preview }: { preview: ICPPreview }) {
  const max = Math.max(...GRADES.flatMap((g) => [preview.current_distribution[g] ?? 0, preview.grade_distribution[g] ?? 0]), 1);
  return (
    <table className="w-full text-xs">
      <caption className="sr-only">Grade distribution, current versus preview</caption>
      <thead className="text-left text-[11px] text-muted">
        <tr>
          <th scope="col" className="pb-1.5 font-medium">Grade</th>
          <th scope="col" className="pb-1.5 font-medium">Distribution</th>
          <th scope="col" className="pb-1.5 text-right font-medium">Now</th>
          <th scope="col" className="pb-1.5 text-right font-medium">Preview</th>
          <th scope="col" className="pb-1.5 text-right font-medium">Change</th>
        </tr>
      </thead>
      <tbody>
        {GRADES.map((g) => {
          const now = preview.current_distribution[g] ?? 0;
          const next = preview.grade_distribution[g] ?? 0;
          const delta = next - now;
          return (
            <tr key={g} className="border-t border-border">
              <td className="py-1.5 pr-2">
                <GradeBadge grade={g} />
              </td>
              <td className="w-1/2 py-1.5 pr-3">
                <div className="space-y-0.5" aria-hidden>
                  <div className="h-1.5 rounded-full bg-subtle/60" style={{ width: `${(now / max) * 100}%` }} />
                  <div className="h-1.5 rounded-full bg-accent" style={{ width: `${(next / max) * 100}%` }} />
                </div>
              </td>
              <td className="tabular py-1.5 text-right text-muted">{num(now)}</td>
              <td className="tabular py-1.5 text-right font-medium text-text">{num(next)}</td>
              <td
                className={cn(
                  "tabular py-1.5 text-right",
                  delta > 0 ? "text-success" : delta < 0 ? "text-danger" : "text-subtle",
                  g === "X" && delta !== 0 && "text-warning",
                )}
              >
                {delta > 0 ? `+${num(delta)}` : delta < 0 ? `−${num(Math.abs(delta))}` : "0"}
              </td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}

export function IcpEditor({ initial, signalTypes, version }: { initial: ICPDefinition; signalTypes: SignalType[]; version: number }) {
  const router = useRouter();
  const [refreshing, startTransition] = useTransition();
  const [def, setDef] = useState<ICPDefinition>(initial);
  const [preview, setPreview] = useState<ICPPreview | null>(null);
  const [previewedDef, setPreviewedDef] = useState<string | null>(null);
  const [busy, setBusy] = useState<"preview" | "save" | null>(null);
  const [errors, setErrors] = useState<FieldError[]>([]);
  const [generalError, setGeneralError] = useState<string | null>(null);
  const [armed, setArmed] = useState(false);
  const [saved, setSaved] = useState<{ version: number; rescored: number } | null>(null);

  const weightSum = CATS.reduce((acc, c) => acc + (Number.isFinite(def.weights[c]) ? def.weights[c] : 0), 0);
  const weightsOk = Math.abs(weightSum - 100) < 0.001;
  const dirty = JSON.stringify(def) !== JSON.stringify(initial);
  const currentKey = JSON.stringify(def);
  const previewStale = preview !== null && previewedDef !== currentKey;

  const bySection = useMemo(() => {
    const out: Record<string, FieldError[]> = {};
    for (const e of errors) (out[sectionFor(e.loc)] ??= []).push(e);
    return out;
  }, [errors]);

  const suggestions = useMemo(
    () => Array.from(new Set([...initial.core_industries, ...initial.adjacent_industries])),
    [initial.core_industries, initial.adjacent_industries],
  );

  function update(next: ICPDefinition) {
    setDef(next);
    setArmed(false);
    setSaved(null);
  }

  /** Keep the payload valid JSON: NaN (empty inputs) would serialize as null. */
  function payload(): ICPDefinition {
    const fix = (n: number) => (Number.isFinite(n) ? n : 0);
    return {
      ...def,
      weights: Object.fromEntries(CATS.map((c) => [c, fix(def.weights[c])])) as unknown as Weights,
      size: Object.fromEntries(Object.entries(def.size).map(([k, v]) => [k, Math.round(fix(v))])) as ICPDefinition["size"],
      positive_signals: Object.fromEntries(Object.entries(def.positive_signals).map(([k, v]) => [k, fix(v)])),
    };
  }

  async function runPreview() {
    setBusy("preview");
    setErrors([]);
    setGeneralError(null);
    try {
      const body = payload();
      const result = await send<ICPPreview>("/icp/preview", "POST", body);
      setPreview(result);
      setPreviewedDef(JSON.stringify(def));
    } catch (e) {
      if (e instanceof ApiFailure && e.details.length) setErrors(e.details);
      else setGeneralError(e instanceof Error ? e.message : "Preview failed");
    } finally {
      setBusy(null);
    }
  }

  async function save() {
    if (!armed) {
      setArmed(true);
      return;
    }
    setArmed(false);
    setBusy("save");
    setErrors([]);
    setGeneralError(null);
    try {
      const result = await send<{ version: number; rescored: number }>("/icp", "PUT", payload());
      setSaved(result);
      setPreview(null);
      startTransition(() => router.refresh());
    } catch (e) {
      if (e instanceof ApiFailure && e.details.length) setErrors(e.details);
      else setGeneralError(e instanceof Error ? e.message : "Save failed");
    } finally {
      setBusy(null);
    }
  }

  function reset() {
    setDef(initial);
    setErrors([]);
    setGeneralError(null);
    setPreview(null);
    setArmed(false);
  }

  const movers = (preview?.biggest_movers ?? []).filter((m) => m.delta !== 0);

  return (
    <Panel
      id="editor"
      title="Tune the model"
      description={`Edit a draft of v${version}, preview the impact on every account, then save it as a new version.`}
      actions={
        dirty ? (
          <Button type="button" size="sm" variant="ghost" onClick={reset}>
            <RotateCcw className="size-3.5" aria-hidden />
            Reset
          </Button>
        ) : null
      }
    >
      <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_minmax(0,26rem)]">
        <div className="space-y-6">
          <fieldset>
            <legend className="text-xs font-semibold text-text">Category weights</legend>
            <div className="mt-2 grid grid-cols-2 gap-2 sm:grid-cols-5">
              {CATS.map((c) => (
                <NumberField
                  key={c}
                  label={c.charAt(0).toUpperCase() + c.slice(1)}
                  value={def.weights[c]}
                  step={1}
                  invalid={!weightsOk || !!bySection.weights}
                  onChange={(v) => update({ ...def, weights: { ...def.weights, [c]: v } })}
                />
              ))}
            </div>
            <p className={cn("mt-1.5 text-[11px]", weightsOk ? "text-muted" : "text-warning")} aria-live="polite">
              Total <span className="tabular font-medium">{num(weightSum, 1)}</span> / 100
              {!weightsOk && " · weights must sum to 100 (the API will reject this; try Preview to see)"}
            </p>
            <FieldErrors errors={bySection.weights ?? []} />
          </fieldset>

          <fieldset>
            <legend className="text-xs font-semibold text-text">Company size (employees)</legend>
            <div className="mt-2 grid grid-cols-2 gap-2 sm:grid-cols-5">
              {SIZE_FIELDS.map((f) => (
                <NumberField
                  key={f.key}
                  label={f.label}
                  value={def.size[f.key]}
                  invalid={!!bySection.size}
                  onChange={(v) => update({ ...def, size: { ...def.size, [f.key]: v } })}
                />
              ))}
            </div>
            <p className="mt-1.5 text-[11px] text-muted">Must satisfy exclude ≤ min ≤ sweet spot from ≤ sweet spot to ≤ max.</p>
            <FieldErrors errors={bySection.size ?? []} />
          </fieldset>

          <fieldset>
            <legend className="text-xs font-semibold text-text">Core industries</legend>
            <div className="mt-2">
              <IndustryEditor
                value={def.core_industries}
                suggestions={suggestions}
                invalid={!!bySection.core_industries}
                onChange={(v) => update({ ...def, core_industries: v })}
              />
            </div>
            <FieldErrors errors={bySection.core_industries ?? []} />
          </fieldset>

          <fieldset>
            <legend className="text-xs font-semibold text-text">Signal max points</legend>
            <p className="mt-0.5 text-[11px] text-muted">0 ignores the signal type. Points are capped by the category budget.</p>
            <div className="mt-2 grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-4">
              {signalTypes.map((s) => (
                <NumberField
                  key={s.key}
                  label={`${s.name} · ${s.category}`}
                  value={def.positive_signals[s.key] ?? 0}
                  step={0.5}
                  invalid={!!bySection.positive_signals}
                  onChange={(v) => update({ ...def, positive_signals: { ...def.positive_signals, [s.key]: v } })}
                />
              ))}
            </div>
            <FieldErrors errors={bySection.positive_signals ?? []} />
          </fieldset>

          {(bySection.other?.length || generalError) && (
            <div role="alert" className="rounded-md border border-danger/30 bg-danger-soft px-3 py-2 text-xs text-danger">
              {generalError && <p>{generalError}</p>}
              {(bySection.other ?? []).map((e, i) => (
                <p key={i}>
                  {e.loc.filter((p) => p !== "body").join(".") || "definition"}: {cleanMsg(e.msg)}
                </p>
              ))}
            </div>
          )}

          <div className="flex flex-wrap items-start gap-2 border-t border-border pt-4">
            <Button type="button" variant="primary" size="sm" onClick={runPreview} disabled={busy !== null} aria-busy={busy === "preview"}>
              {busy === "preview" && <Loader2 className="size-3.5 animate-spin" aria-hidden />}
              {busy === "preview" ? "Scoring every account…" : "Preview impact"}
            </Button>
            <div className="flex flex-col items-start gap-1">
              <Button
                type="button"
                variant={armed ? "danger" : "secondary"}
                size="sm"
                onClick={save}
                disabled={busy !== null || refreshing || !dirty}
                aria-busy={busy === "save"}
                title={dirty ? undefined : "Change something first"}
              >
                {busy === "save" || refreshing ? "Saving and rescoring…" : armed ? `Confirm: save v${version + 1} and rescore` : "Save as new version"}
              </Button>
              {armed && (
                <span className="flex max-w-sm items-start gap-1 text-[11px] text-warning">
                  <TriangleAlert className="mt-px size-3 shrink-0" aria-hidden />
                  Saving creates v{version + 1}, makes it active, and rescores every account. Grades, routing and priorities may change.
                </span>
              )}
            </div>
            {saved && (
              <span role="status" className="self-center text-xs text-success">
                Saved v{saved.version} · rescored {num(saved.rescored)} accounts.
              </span>
            )}
          </div>
        </div>

        <aside aria-label="Preview results" className="space-y-4">
          {preview ? (
            <>
              <div className="rounded-md border border-border p-3">
                <div className="mb-2 flex items-baseline justify-between gap-2">
                  <h3 className="text-xs font-semibold text-text">Grade distribution</h3>
                  <span className="text-[11px] text-muted">{num(preview.accounts_scored)} accounts</span>
                </div>
                {previewStale && (
                  <p className="mb-2 text-[11px] text-warning">Edited since this preview; run it again to update.</p>
                )}
                <DistributionTable preview={preview} />
                <div className="mt-2 flex gap-3 text-[11px] text-muted">
                  <span className="inline-flex items-center gap-1">
                    <span className="h-1.5 w-3 rounded-full bg-subtle/60" aria-hidden /> Now
                  </span>
                  <span className="inline-flex items-center gap-1">
                    <span className="h-1.5 w-3 rounded-full bg-accent" aria-hidden /> Preview
                  </span>
                </div>
              </div>
              <div className="rounded-md border border-border p-3">
                <h3 className="mb-2 text-xs font-semibold text-text">Biggest movers</h3>
                {movers.length ? (
                  <ul className="divide-y divide-border text-xs">
                    {movers.map((m) => (
                      <li key={m.account_id} className="flex items-center justify-between gap-2 py-1.5">
                        <Link href={`/accounts/${m.account_id}`} className="min-w-0 truncate hover:underline">
                          {m.name}
                        </Link>
                        <span className="tabular flex shrink-0 items-center gap-1.5">
                          <span className="text-muted">
                            {m.from} → {m.to}
                          </span>
                          <span className={cn("inline-flex items-center font-medium", m.delta > 0 ? "text-success" : "text-danger")}>
                            {m.delta > 0 ? <ArrowUp className="size-3" aria-hidden /> : <ArrowDown className="size-3" aria-hidden />}
                            {Math.abs(m.delta)}
                          </span>
                        </span>
                      </li>
                    ))}
                  </ul>
                ) : (
                  <p className="text-xs text-muted">No account&apos;s score changes with this draft.</p>
                )}
              </div>
              <p className="text-[11px] text-muted">
                Preview rescores with today&apos;s signal ages, so a few grades can differ from the stored scores even with no edits.
                Nothing is saved.
              </p>
            </>
          ) : (
            <div className="rounded-md border border-dashed border-border px-4 py-8 text-center">
              <p className="text-sm font-medium text-text">No preview yet</p>
              <p className="mx-auto mt-1 max-w-xs text-xs text-muted">
                Change a weight, the size band, industries or signal points, then preview how grades shift across every account before
                saving anything.
              </p>
            </div>
          )}
        </aside>
      </div>
    </Panel>
  );
}
