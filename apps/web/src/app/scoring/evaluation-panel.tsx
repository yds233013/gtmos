import { Badge } from "@/components/ui/badge";
import { Panel } from "@/components/ui/panel";
import { Table, Td, Th, THead, Tr } from "@/components/ui/table";
import { num, pct } from "@/lib/format";
import { cn } from "@/lib/utils";

import type { ScoringEvaluation, ScoringBucket, ScoringVariant } from "./evaluation-types";

/** An AUC whose interval crosses this is not distinguishable from guessing. */
const COIN_FLIP = 0.5;

function Ci({ low, high }: { low: number; high: number }) {
  return (
    <span className="tabular whitespace-nowrap text-[11px] text-muted">
      {pct(low, 0)}–{pct(high, 0)}
    </span>
  );
}

function BucketRows({ buckets, label }: { buckets: ScoringBucket[]; label: string }) {
  return (
    <Table>
      <THead>
        <tr>
          <Th>{label}</Th>
          <Th align="right">Accounts</Th>
          <Th align="right">Converted</Th>
          <Th align="right">Rate</Th>
          <Th align="right">95% CI</Th>
          <Th align="right">Lift</Th>
        </tr>
      </THead>
      <tbody>
        {buckets.map((b) => (
          <Tr key={b.label}>
            <Td className="text-xs font-medium">
              {b.label}
              {b.small_sample && (
                <Badge tone="warning" className="ml-1.5" title="Fewer than 30 accounts: read the interval, not the rate">
                  small n
                </Badge>
              )}
            </Td>
            <Td align="right" className="text-xs">
              {num(b.n)}
            </Td>
            <Td align="right" className="text-xs">
              {num(b.positives)}
            </Td>
            <Td align="right" className="text-xs font-medium">
              {pct(b.rate, 1)}
            </Td>
            <Td align="right">
              <Ci low={b.ci_low} high={b.ci_high} />
            </Td>
            <Td align="right" className={cn("text-xs tabular", b.lift >= 1 ? "text-text" : "text-muted")}>
              {b.lift.toFixed(2)}×
            </Td>
          </Tr>
        ))}
      </tbody>
    </Table>
  );
}

function VariantRow({ v }: { v: ScoringVariant }) {
  const [low, high] = v.auc_ci ?? [0, 1];
  const inconclusive = low <= COIN_FLIP;
  return (
    <li className="border-b border-border py-2.5 last:border-0">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <span className="text-xs font-medium text-text">{v.label}</span>
        <span className="inline-flex items-baseline gap-2">
          <span className="tabular text-sm font-semibold text-text">{v.auc?.toFixed(3) ?? "—"}</span>
          <span className="tabular text-[11px] text-muted">
            {low.toFixed(3)}–{high.toFixed(3)}
          </span>
          {inconclusive && (
            <Badge tone="warning" title="The interval includes 0.5, so this ranking is not distinguishable from random">
              Not conclusive
            </Badge>
          )}
        </span>
      </div>
      <p className="mt-1 text-[11px] text-muted">{v.leakage}</p>
    </li>
  );
}

/**
 * The score's report card. A scoring page that only explains *how* points are awarded invites the
 * obvious question — does any of it predict anything? — so the answer sits next to the model, with
 * the leakage and the small samples stated rather than rounded away.
 */
export function EvaluationPanel({ evaluation }: { evaluation: ScoringEvaluation | null }) {
  if (!evaluation) return null;
  const outcome = evaluation.outcomes.meeting;
  if (!outcome) return null;
  const pop = evaluation.population;
  const delta = outcome.leakage_delta;
  const sel = outcome.selection_effect;
  const variants = [outcome.variants.structural, outcome.variants.pre_engagement, outcome.variants.total];

  return (
    <Panel
      title="Does the score work?"
      description={`Backtest against realised outcomes · ${num(pop.evaluated)} contacted accounts · outcome: ${outcome.label.toLowerCase()}`}
      bodyClassName="p-0"
    >
      <div className="grid gap-5 border-b border-border p-4 lg:grid-cols-2">
        <div>
          <h3 className="text-xs font-medium text-text">Ranking power by score variant (AUC)</h3>
          <p className="mt-1 text-[11px] text-muted">
            The probability that a converting account outranks a non-converting one. 0.5 is a coin flip.
          </p>
          <ul className="mt-2">
            {variants.map((v) => (
              <VariantRow key={v.label} v={v} />
            ))}
          </ul>
        </div>
        <div className="space-y-3 text-[11px] text-muted">
          {delta.available && (
            <div className="rounded-md border border-border bg-panel-2/60 p-3">
              <div className="text-xs font-medium text-text">
                Leakage: {delta.delta > 0 ? "+" : ""}
                {delta.delta.toFixed(3)} AUC
              </div>
              <p className="mt-1">{delta.interpretation}</p>
            </div>
          )}
          {sel.available && (
            <div className="rounded-md border border-border bg-panel-2/60 p-3">
              <div className="text-xs font-medium text-text">
                Selection effect: {sel.contacted_only_auc.toFixed(3)} on contacted vs {sel.all_accounts_auc.toFixed(3)} on all
              </div>
              <p className="mt-1">{sel.note}</p>
            </div>
          )}
        </div>
      </div>

      <div className="border-b border-border px-4 py-2 text-[11px] text-muted">
        Conversion by grade — the bands are only useful if they order conversion.
      </div>
      <BucketRows buckets={outcome.by_grade} label="Grade" />

      <div className="border-t border-border px-4 py-3">
        <h3 className="text-xs font-medium text-text">Caveats</h3>
        <ul className="mt-1.5 list-disc space-y-1 pl-4 text-[11px] text-muted">
          {evaluation.caveats.map((c) => (
            <li key={c}>{c}</li>
          ))}
        </ul>
      </div>
    </Panel>
  );
}
