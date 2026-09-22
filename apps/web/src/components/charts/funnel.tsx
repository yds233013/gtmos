import { num, pct, titleCase } from "@/lib/format";

export interface FunnelStage {
  stage: string;
  accounts: number;
  conversion_from_previous: number | null;
  conversion_from_cohort?: number | null;
}

/** Stage funnel as aligned bars with step conversion; a table in disguise, so it stays readable. */
export function FunnelBars({ stages }: { stages: FunnelStage[] }) {
  const max = Math.max(...stages.map((s) => s.accounts), 1);
  return (
    <table className="w-full text-xs">
      <caption className="sr-only">Cohort funnel: accounts reaching each stage</caption>
      <thead className="text-[10px] uppercase tracking-wide text-subtle">
        <tr>
          <th className="pb-1 text-left font-medium">Stage</th>
          <th className="pb-1 text-left font-medium">Accounts</th>
          <th className="pb-1 pl-3 text-right font-medium" title="Conversion from the previous stage">
            Step
          </th>
          <th className="pb-1 pl-3 text-right font-medium" title="Share of the contacted cohort">
            Cohort
          </th>
        </tr>
      </thead>
      <tbody>
        {stages.map((s) => (
          <tr key={s.stage}>
            <td className="w-24 py-1.5 pr-3 text-muted">{titleCase(s.stage)}</td>
            <td className="py-1.5">
              <div className="flex items-center gap-2">
                <div className="h-5 flex-1 overflow-hidden rounded bg-panel-2">
                  <div
                    className="h-full rounded bg-accent/80"
                    style={{ width: `${Math.max((s.accounts / max) * 100, s.accounts ? 1.5 : 0)}%` }}
                  />
                </div>
                <span className="tabular w-14 text-right font-medium text-text">{num(s.accounts)}</span>
              </div>
            </td>
            <td className="tabular w-14 py-1.5 pl-3 text-right text-muted">
              {s.conversion_from_previous === null ? "—" : pct(s.conversion_from_previous, 0)}
            </td>
            <td className="tabular w-14 py-1.5 pl-3 text-right text-subtle">
              {s.conversion_from_cohort === null || s.conversion_from_cohort === undefined
                ? "—"
                : pct(s.conversion_from_cohort, 0)}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
