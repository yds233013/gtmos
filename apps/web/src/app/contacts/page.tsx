import { Search } from "lucide-react";
import Link from "next/link";

import { AutoSubmitSelect } from "@/components/revenue/filter-controls";
import { Pagination } from "@/components/revenue/pagination";
import { apiQuery, first, hrefWith, intParam, oneOf } from "@/components/revenue/query";
import { Badge, DemoBadge, StatusBadge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { PageHeader } from "@/components/ui/page-header";
import { Panel } from "@/components/ui/panel";
import { EmptyState, ErrorState } from "@/components/ui/states";
import { Table, Td, Th, THead, Tr } from "@/components/ui/table";
import { api, settle } from "@/lib/api";
import { num, titleCase } from "@/lib/format";
import type { Contact, Paged } from "@/lib/types";
import { cn } from "@/lib/utils";

export const metadata = { title: "Contacts" };

const BASE = "/contacts";
const PAGE_SIZE = 50;
const EMAIL_STATUSES = ["valid", "risky", "invalid", "unknown"] as const;
const ROLES = ["champion", "technical_evaluator", "economic_buyer", "executive_sponsor", "end_user"] as const;

const EMAIL_HINT: Record<string, string> = {
  valid: "Mailbox verified; safe to sequence",
  risky: "Catch-all or low-confidence verification; send with care",
  invalid: "Bounces; GTMOS will not draft email to this contact",
  unknown: "Not verified yet",
};

export default async function ContactsPage(props: PageProps<"/contacts">) {
  const sp = await props.searchParams;
  const q = first(sp.q)?.slice(0, 100);
  const emailStatus = oneOf(sp.email_status, EMAIL_STATUSES);
  const role = oneOf(sp.role, ROLES);
  const page = intParam(sp.page, 1);
  const current = { q, email_status: emailStatus, role };

  const [list, ...statusTotals] = await settle(
    api<Paged<Contact>>(`/contacts?${apiQuery({ ...current, page, page_size: PAGE_SIZE })}`),
    ...EMAIL_STATUSES.map((s) => api<Paged<Contact>>(`/contacts?${apiQuery({ q, role, email_status: s, page_size: 1 })}`)),
  );

  if (!list) {
    return (
      <div>
        <PageHeader title="Contacts" description="People at target accounts, with verification status and buying roles." />
        <ErrorState title="Couldn't load contacts" message="The GTMOS API did not respond. Check that the backend is running." />
      </div>
    );
  }

  const hasDemo = list.items.some((c) => c.data_origin === "demo");
  const filtered = Boolean(q || emailStatus || role);

  return (
    <div className="space-y-4">
      <PageHeader
        title="Contacts"
        eyebrow={
          <span className="inline-flex items-center gap-2">
            {num(list.total)} {filtered ? "matching" : "total"} {hasDemo && <DemoBadge />}
          </span>
        }
        description="People at target accounts. Email status gates outreach (invalid addresses and do-not-contact records are never drafted), and buying roles come from GTMOS committee inference."
      />

      <Panel bodyClassName="space-y-3">
        <form method="get" action={BASE} className="grid grid-cols-2 gap-3 sm:flex sm:flex-wrap sm:items-end" role="search">
          <div className="col-span-2 flex min-w-0 flex-col gap-1 sm:w-72">
            <label htmlFor="contacts-q" className="text-[11px] font-medium text-muted">
              Search
            </label>
            <div className="relative">
              <Search className="pointer-events-none absolute left-2 top-1/2 size-3.5 -translate-y-1/2 text-subtle" aria-hidden />
              <input
                id="contacts-q"
                type="search"
                name="q"
                defaultValue={q ?? ""}
                maxLength={100}
                placeholder="Name, email or title"
                className="h-8 w-full rounded-md border border-border bg-panel pl-7 pr-2 text-xs text-text placeholder:text-subtle hover:border-border-strong"
              />
            </div>
          </div>
          <AutoSubmitSelect
            name="email_status"
            label="Email status"
            value={emailStatus}
            options={[{ value: "", label: "Any status" }, ...EMAIL_STATUSES.map((s) => ({ value: s, label: titleCase(s) }))]}
            className="sm:w-36"
          />
          <AutoSubmitSelect
            name="role"
            label="Buying role"
            value={role}
            options={[{ value: "", label: "Any role" }, ...ROLES.map((r) => ({ value: r, label: titleCase(r) }))]}
            className="sm:w-44"
          />
          <div className="col-span-2 flex items-center gap-2 sm:col-span-1">
            <Button type="submit" variant="secondary">
              Search
            </Button>
            {filtered && (
              <Link href={BASE} className="text-xs text-accent-text hover:underline">
                Clear
              </Link>
            )}
          </div>
        </form>

        <nav aria-label="Filter by email status" className="flex flex-wrap gap-1.5">
          {EMAIL_STATUSES.map((s, i) => {
            const total = statusTotals[i]?.total;
            const active = emailStatus === s;
            return (
              <Link
                key={s}
                href={hrefWith(BASE, current, { email_status: active ? null : s })}
                aria-current={active ? "page" : undefined}
                title={EMAIL_HINT[s]}
                className={cn(
                  "inline-flex items-center gap-1.5 rounded-md border border-border bg-panel px-2 py-1 text-xs text-text hover:bg-panel-2",
                  active && "border-transparent bg-accent-soft text-accent-text hover:bg-accent-soft",
                )}
              >
                {titleCase(s)} <span className="tabular text-subtle">{total === undefined ? "—" : num(total)}</span>
              </Link>
            );
          })}
        </nav>
      </Panel>

      <Panel bodyClassName="p-0">
        {list.items.length === 0 ? (
          <EmptyState
            title="No contacts match"
            description={q ? `Nothing matches “${q}” with these filters. Search covers name, email and title.` : "No contacts match these filters."}
            action={
              filtered ? (
                <Link href={BASE} className="text-xs text-accent-text hover:underline">
                  Clear filters
                </Link>
              ) : undefined
            }
          />
        ) : (
          <>
            <Table>
              <THead>
                <tr>
                  <Th>Contact</Th>
                  <Th>Account</Th>
                  <Th>Email</Th>
                  <Th>Buying roles</Th>
                  <Th>Seniority</Th>
                  <Th>Lifecycle</Th>
                  <Th>Source</Th>
                </tr>
              </THead>
              <tbody>
                {list.items.map((c) => (
                  <Tr key={c.id}>
                    <Td className="min-w-48">
                      <div className="flex items-center gap-1.5">
                        <span className="font-medium text-text">{c.full_name}</span>
                        {c.do_not_contact && (
                          <Badge tone="danger" title="Do not contact: excluded from every outreach workflow">
                            DNC
                          </Badge>
                        )}
                      </div>
                      <div className="text-xs text-muted">{c.title ?? "No title"}</div>
                    </Td>
                    <Td className="whitespace-nowrap">
                      {c.account_id ? (
                        <Link href={`/accounts/${c.account_id}`} className="hover:underline">
                          {c.account_name ?? "Account"}
                        </Link>
                      ) : (
                        <span className="text-xs text-warning">Unmatched</span>
                      )}
                    </Td>
                    <Td className="whitespace-nowrap">
                      <div className="font-mono text-[11px] text-text">{c.email ?? "—"}</div>
                      <div className="mt-1" title={EMAIL_HINT[c.email_status]}>
                        <StatusBadge status={c.email_status} />
                      </div>
                    </Td>
                    <Td>
                      {c.roles.length ? (
                        <div className="flex flex-wrap gap-1">
                          {c.roles.map((r) => (
                            <Badge key={r} tone={r === role ? "accent" : "neutral"}>
                              {titleCase(r)}
                            </Badge>
                          ))}
                        </div>
                      ) : (
                        <span className="text-xs text-subtle">—</span>
                      )}
                    </Td>
                    <Td className="whitespace-nowrap text-xs">
                      <div>{titleCase(c.seniority)}</div>
                      <div className="text-muted">{titleCase(c.department)}</div>
                    </Td>
                    <Td className="whitespace-nowrap text-xs">{titleCase(c.lifecycle_stage)}</Td>
                    <Td className="whitespace-nowrap">
                      <div className="flex items-center gap-1.5">
                        <span className="font-mono text-[11px] text-muted">{c.source}</span>
                        {c.data_origin === "demo" && <DemoBadge />}
                      </div>
                    </Td>
                  </Tr>
                ))}
              </tbody>
            </Table>
            <Pagination base={BASE} params={current} page={page} pageSize={PAGE_SIZE} total={list.total} noun="contacts" />
          </>
        )}
      </Panel>
    </div>
  );
}
