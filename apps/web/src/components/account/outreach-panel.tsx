import Link from "next/link";

import { ActionButton } from "@/components/ui/action-button";
import { Badge, StatusBadge } from "@/components/ui/badge";
import { Panel } from "@/components/ui/panel";
import { EmptyState } from "@/components/ui/states";
import { relTime, titleCase } from "@/lib/format";
import type { AccountDetail } from "@/lib/types";

export function OutreachPanel({ data }: { data: AccountDetail }) {
  const drafts = data.drafts;
  const contacts = new Map(data.contacts.map((c) => [c.id, c]));
  return (
    <Panel
      title="Personalized outreach"
      description="Built as verified signal → pain hypothesis → value proposition → proof → CTA. Guardrails run on every draft; nothing is ever sent from GTMOS."
      actions={
        <ActionButton path={`/accounts/${data.account.id}/drafts`} body={{}} variant="primary">
          Draft outreach for champion
        </ActionButton>
      }
      bodyClassName="p-0"
    >
      {drafts.length === 0 ? (
        <EmptyState title="No drafts yet" description="Drafts use the latest research brief and the strongest verified signal." />
      ) : (
        <ul className="divide-y divide-border">
          {drafts.map((d) => {
            const failing = d.guardrails.filter((g) => !g.passed);
            const c = d.contact_id ? contacts.get(d.contact_id) : null;
            return (
              <li key={d.id} className="px-4 py-3">
                <div className="flex flex-wrap items-center gap-2 text-xs">
                  <Badge>{titleCase(d.channel)}</Badge>
                  <StatusBadge status={d.status} />
                  <span className="text-muted">to {c?.full_name ?? "unknown"}</span>
                  <span className="text-muted">· angle: {titleCase(d.angle)}</span>
                  {failing.length > 0 ? (
                    <Badge tone={failing.some((g) => g.blocking) ? "danger" : "warning"}>{failing.length} guardrail issue(s)</Badge>
                  ) : (
                    <Badge tone="success">Guardrails pass</Badge>
                  )}
                  <span className="ml-auto text-muted">{relTime(d.created_at)}</span>
                </div>
                {d.subject && <div className="mt-2 text-sm font-medium">{d.subject}</div>}
                <pre className="mt-1 max-h-40 overflow-hidden whitespace-pre-wrap font-sans text-xs leading-relaxed text-muted">{d.body}</pre>
                <Link href={`/approvals?id=${d.id}&status=${d.status}`} className="mt-2 inline-block text-xs text-accent-text hover:underline">
                  Open in approval queue →
                </Link>
              </li>
            );
          })}
        </ul>
      )}
    </Panel>
  );
}
