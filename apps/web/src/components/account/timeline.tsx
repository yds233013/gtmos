import { Badge } from "@/components/ui/badge";
import { Panel } from "@/components/ui/panel";
import { EmptyState } from "@/components/ui/states";
import { dateTime, titleCase } from "@/lib/format";
import type { AccountDetail } from "@/lib/types";

type Item = { at: string; kind: "activity" | "stage" | "signal"; title: string; detail?: string | null; meta?: string | null };

export function Timeline({ data }: { data: AccountDetail }) {
  const items: Item[] = [
    ...data.activities
      .filter((a) => a.type !== "email_opened")
      .map((a) => ({
        at: a.occurred_at,
        kind: "activity" as const,
        title: `${titleCase(a.type)}${a.contact_name ? ` · ${a.contact_name}` : ""}`,
        detail: a.summary ?? a.subject,
        meta: a.campaign,
      })),
    ...data.stage_history.map((t) => ({
      at: t.changed_at,
      kind: "stage" as const,
      title: `Stage: ${titleCase(t.from_stage ?? "—")} → ${titleCase(t.to_stage)}`,
      detail: t.reason,
      meta: t.changed_by,
    })),
    ...data.signals.map((s) => ({
      at: s.observed_at,
      kind: "signal" as const,
      title: `Signal: ${s.title}`,
      detail: s.explanation,
      meta: s.source,
    })),
  ].sort((a, b) => b.at.localeCompare(a.at));

  if (!items.length) return <EmptyState title="No activity yet" />;
  const tone = { activity: "neutral", stage: "accent", signal: "info" } as const;
  return (
    <Panel title="Activity timeline" description="Sales activities, stage changes and buying signals (email opens hidden: unreliable)" bodyClassName="p-0">
      <ol className="divide-y divide-border">
        {items.slice(0, 120).map((i, idx) => (
          <li key={idx} className="grid grid-cols-[110px_1fr] gap-3 px-4 py-2 text-xs sm:grid-cols-[140px_1fr]">
            <time className="tabular text-muted" dateTime={i.at}>
              {dateTime(i.at)}
            </time>
            <div className="min-w-0">
              <div className="flex flex-wrap items-center gap-1.5">
                <Badge tone={tone[i.kind]}>{i.kind}</Badge>
                <span className="font-medium">{i.title}</span>
                {i.meta && <span className="text-muted">· {i.meta}</span>}
              </div>
              {i.detail && <p className="mt-0.5 text-muted">{i.detail}</p>}
            </div>
          </li>
        ))}
      </ol>
    </Panel>
  );
}
