import { GradeBadge } from "@/components/ui/badge";
import { Panel } from "@/components/ui/panel";
import { ScoreBar } from "@/components/ui/score-bar";
import { relTime } from "@/lib/format";
import type { AccountDetail, ScoreComponent } from "@/lib/types";

const CATEGORY_LABEL: Record<string, string> = {
  fit: "Fit",
  intent: "Intent",
  timing: "Timing",
  technical: "Technical",
  engagement: "Engagement",
};
const ORDER = ["fit", "intent", "timing", "technical", "engagement"] as const;
const BUDGET: Record<string, number> = { fit: 35, intent: 25, timing: 15, technical: 15, engagement: 10 };

function fmt(n: number): string {
  return Number.isInteger(n) ? String(n) : n.toFixed(1);
}

export function ScorePanel({ score }: { score: NonNullable<AccountDetail["score"]> }) {
  const byCat = new Map<string, ScoreComponent[]>();
  for (const c of score.components) byCat.set(c.category, [...(byCat.get(c.category) ?? []), c]);
  return (
    <Panel
      title="Why this score"
      description={`ICP v${score.icp_version} · computed ${relTime(score.computed_at)} · trigger: ${score.trigger}`}
      actions={<span className="font-mono text-[10px] text-subtle" title="SHA-256 of all scoring inputs">inputs {score.inputs_hash.slice(0, 10)}</span>}
    >
      <div className="flex flex-col gap-6 md:flex-row">
        <div className="md:w-56 md:shrink-0">
          <div className="flex items-baseline gap-2">
            <span className="tabular text-4xl font-semibold tracking-tight">{score.total}</span>
            <span className="text-sm text-muted">/ 100</span>
            <GradeBadge grade={score.grade} />
          </div>
          {score.excluded && <p className="mt-2 text-xs text-danger">Excluded: {score.exclusion_reason}</p>}
          <dl className="mt-4 space-y-2">
            {ORDER.map((k) => (
              <div key={k}>
                <div className="flex justify-between text-xs">
                  <dt className="text-muted">{CATEGORY_LABEL[k]}</dt>
                  <dd className="tabular font-medium">
                    {fmt(score[k])}
                    <span className="text-subtle">/{BUDGET[k]}</span>
                  </dd>
                </div>
                <ScoreBar value={score[k]} max={BUDGET[k]} className="mt-1" />
              </div>
            ))}
          </dl>
          <p className="mt-4 text-xs leading-relaxed text-muted">{score.summary}</p>
        </div>
        <div className="min-w-0 flex-1 space-y-4">
          {ORDER.map((cat) => {
            const comps = byCat.get(cat) ?? [];
            return (
              <div key={cat}>
                <h3 className="mb-1.5 text-xs font-medium uppercase tracking-wide text-muted">{CATEGORY_LABEL[cat]}</h3>
                {comps.length === 0 ? (
                  <p className="text-xs text-subtle">No qualifying {cat} signals.</p>
                ) : (
                  <ul className="divide-y divide-border rounded-md border border-border">
                    {comps.map((c) => (
                      <li key={c.id} className="grid grid-cols-[1fr_auto] gap-x-4 gap-y-1 px-3 py-2">
                        <span className="text-xs font-medium">{c.label}</span>
                        <span className="tabular text-xs font-medium">
                          {fmt(c.points)} <span className="text-subtle">/ {fmt(c.max_points)}</span>
                        </span>
                        <span className="col-span-2 text-xs text-muted">{c.explanation}</span>
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            );
          })}
        </div>
      </div>
    </Panel>
  );
}
