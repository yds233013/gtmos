import { Badge } from "@/components/ui/badge";
import { Panel } from "@/components/ui/panel";
import { EmptyState } from "@/components/ui/states";
import { pct, titleCase } from "@/lib/format";
import type { AccountDetail } from "@/lib/types";

import { RoleOverride } from "./role-override";

const ROLE_ORDER = ["champion", "economic_buyer", "technical_evaluator", "executive_sponsor", "end_user"];
const ROLE_HELP: Record<string, string> = {
  champion: "Feels the pain, sells internally",
  economic_buyer: "Controls the budget",
  technical_evaluator: "Runs the evaluation",
  executive_sponsor: "Sponsors the strategic bet",
  end_user: "Uses it daily",
};

export function CommitteePanel({ data }: { data: AccountDetail }) {
  const primaries = data.committee.filter((r) => r.rank === 1);
  const byRole = new Map(primaries.map((r) => [r.role, r]));
  const backups = data.committee.filter((r) => r.rank > 1);
  const contactOptions = data.contacts
    .filter((c) => !c.do_not_contact)
    .map((c) => ({ id: c.id, label: `${c.full_name} · ${c.title ?? "—"}` }));
  return (
    <div className="space-y-4">
      <Panel
        title="Buying committee"
        description="Inferred from title, seniority, department, product usage and engagement. Manual overrides always win and survive recomputation."
      >
        <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
          {ROLE_ORDER.map((role) => {
            const r = byRole.get(role);
            return (
              <div key={role} className="rounded-md border border-border p-3">
                <div className="flex items-center justify-between gap-2">
                  <div>
                    <div className="text-xs font-medium">{titleCase(role)}</div>
                    <div className="text-[11px] text-muted">{ROLE_HELP[role]}</div>
                  </div>
                  {r?.is_manual_override ? <Badge tone="accent">Manual</Badge> : r ? <Badge>{pct(r.confidence, 0)} conf.</Badge> : null}
                </div>
                {r?.contact ? (
                  <div className="mt-3">
                    <div className="text-sm font-medium">{r.contact.name}</div>
                    <div className="text-xs text-muted">{r.contact.title}</div>
                    <ul className="mt-2 space-y-0.5 text-[11px] text-muted">
                      {r.rationale.slice(0, 4).map((why) => (
                        <li key={why}>· {why}</li>
                      ))}
                    </ul>
                  </div>
                ) : (
                  <p className="mt-3 text-xs text-warning">Unfilled: source a contact for this role.</p>
                )}
                <div className="mt-3">
                  <RoleOverride accountId={data.account.id} role={role} options={contactOptions} current={r?.contact?.id ?? null} manual={!!r?.is_manual_override} />
                </div>
              </div>
            );
          })}
        </div>
        {backups.length > 0 && (
          <p className="mt-3 text-[11px] text-muted">
            Backups ranked: {backups.map((b) => `${b.contact?.name} (${titleCase(b.role)} #${b.rank})`).join(", ")}
          </p>
        )}
      </Panel>

      <Panel title={`Contacts (${data.contacts.length})`} bodyClassName="p-0">
        {data.contacts.length === 0 ? (
          <EmptyState title="No contacts" />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead className="border-b border-border text-left text-[11px] uppercase tracking-wide text-muted">
                <tr>
                  <th className="px-4 py-2 font-medium">Name</th>
                  <th className="px-2 py-2 font-medium">Title</th>
                  <th className="px-2 py-2 font-medium">Email</th>
                  <th className="px-2 py-2 font-medium">Roles</th>
                  <th className="px-4 py-2 font-medium">Lifecycle</th>
                </tr>
              </thead>
              <tbody>
                {data.contacts.map((c) => (
                  <tr key={c.id} className="border-b border-border last:border-0">
                    <td className="px-4 py-1.5 font-medium">{c.full_name}</td>
                    <td className="px-2 py-1.5 text-muted">{c.title ?? "—"}</td>
                    <td className="px-2 py-1.5">
                      <span className="font-mono text-[11px]">{c.email ?? "—"}</span>{" "}
                      {c.email_status !== "valid" && (
                        <Badge tone={c.email_status === "invalid" ? "danger" : "warning"}>{c.email_status}</Badge>
                      )}
                      {c.do_not_contact && <Badge tone="danger">DNC</Badge>}
                    </td>
                    <td className="px-2 py-1.5">
                      <div className="flex flex-wrap gap-1">
                        {c.roles.map((r) => (
                          <Badge key={r} tone="accent">
                            {titleCase(r)}
                          </Badge>
                        ))}
                      </div>
                    </td>
                    <td className="px-4 py-1.5 text-muted">{titleCase(c.lifecycle_stage)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Panel>
    </div>
  );
}
