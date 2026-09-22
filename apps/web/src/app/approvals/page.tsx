import { CircleCheck, CircleX, Info, Mail, MessageSquare, PhoneCall, ShieldAlert, ShieldCheck } from "lucide-react";
import Link from "next/link";

import { first, oneOf } from "@/components/revenue/query";
import { ActionButton } from "@/components/ui/action-button";
import { Badge, DemoBadge, StatusBadge } from "@/components/ui/badge";
import { PageHeader } from "@/components/ui/page-header";
import { Panel } from "@/components/ui/panel";
import { EmptyState, ErrorState } from "@/components/ui/states";
import { api } from "@/lib/api";
import { dateTime, num, pct, relTime, titleCase } from "@/lib/format";
import { cn } from "@/lib/utils";

import { MessageCard } from "./message-card";
import { ReasonTransition } from "./reason-transition";
import type { DraftList, DraftRow, DraftStatus } from "./types";

export const metadata = { title: "Approvals" };

const BASE = "/approvals";
const TABS = ["review", "approved", "ready", "draft", "rejected", "all"] as const;
type Tab = (typeof TABS)[number];

const TAB_LABEL: Record<Tab, string> = {
  review: "In review",
  approved: "Approved",
  ready: "Ready",
  draft: "Draft",
  rejected: "Rejected",
  all: "All",
};

const STATUS_HELP: Record<DraftStatus, string> = {
  draft: "Not yet submitted. Submit it for review when the wording is right.",
  review: "Waiting for a human decision. Approval is blocked while any blocking guardrail fails.",
  approved: "A human approved this wording. Mark it ready to hand it to the sequencer.",
  ready: "Handed off to the sequencer. GTMOS will not send it; a person does, from the sequencer.",
  rejected: "Rejected. Reopen it as a draft to rework it.",
};

const CHANNEL: Record<DraftRow["channel"], { label: string; icon: typeof Mail }> = {
  email: { label: "Email", icon: Mail },
  linkedin: { label: "LinkedIn", icon: MessageSquare },
  call_prep: { label: "Call prep", icon: PhoneCall },
};

function tabHref(tab: Tab, id?: string): string {
  const q = new URLSearchParams();
  if (tab !== "review") q.set("status", tab);
  if (id) q.set("id", id);
  const s = q.toString();
  return s ? `${BASE}?${s}` : BASE;
}

/** Evidence refs cited in the message body, e.g. [E3]. */
function citedRefs(d: DraftRow): Set<string> {
  const refs = new Set<string>();
  for (const m of d.body.matchAll(/\[(E\d+)\]/g)) refs.add(m[1]);
  if (d.reasoning_chain.signal?.ref) refs.add(d.reasoning_chain.signal.ref);
  return refs;
}

export default async function ApprovalsPage(props: PageProps<"/approvals">) {
  const sp = await props.searchParams;
  const tab: Tab = oneOf(sp.status, TABS) ?? "review";
  const selectedId = first(sp.id);

  let list: DraftList;
  try {
    list = await api<DraftList>(tab === "all" ? "/drafts" : `/drafts?status=${tab}`);
  } catch (e) {
    return (
      <div>
        <PageHeader title="Approvals" description="Human review of every outbound draft before it leaves GTMOS." />
        <ErrorState title="Couldn't load the approval queue" message={e instanceof Error ? e.message : undefined} />
      </div>
    );
  }

  let selected: DraftRow | undefined = selectedId ? list.items.find((d) => d.id === selectedId) : list.items[0];
  let movedOut = false;
  if (selectedId && !selected) {
    // The draft may have moved to another status (e.g. just approved); still show it.
    try {
      const all = await api<DraftList>("/drafts");
      selected = all.items.find((d) => d.id === selectedId);
      movedOut = Boolean(selected);
    } catch {
      selected = undefined;
    }
  }

  const counts = list.counts;
  const allCount = Object.values(counts).reduce((s, n) => s + (n ?? 0), 0);

  return (
    <div className="space-y-4">
      <PageHeader
        title="Approvals"
        eyebrow={
          <span className="inline-flex items-center gap-2">
            {num(counts.review ?? 0)} awaiting review <DemoBadge />
          </span>
        }
        description="Every outbound draft, AI or deterministic, stops here for a human. Each one shows the signal it is anchored on, the reasoning behind the angle, the evidence it cites, and the guardrails it had to pass."
      />

      <div className="flex items-start gap-2.5 rounded-lg border border-info/30 bg-info-soft px-4 py-3 text-xs text-text">
        <Info className="mt-0.5 size-4 shrink-0 text-info" aria-hidden />
        <p>
          <span className="font-semibold">GTMOS never sends messages.</span> Approving records a human decision. Marking a
          draft <span className="font-medium">Ready</span> hands it off to your sequencer, where a person sends it under that
          tool&apos;s own limits and unsubscribe handling. Nothing on this page contacts anyone.
        </p>
      </div>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-[minmax(0,340px)_minmax(0,1fr)]">
        {/* Queue */}
        <section aria-label="Draft queue" className="min-w-0 overflow-hidden rounded-lg border border-border bg-panel lg:self-start">
          <nav aria-label="Filter by status" className="flex gap-1 overflow-x-auto border-b border-border px-2">
            {TABS.map((t) => {
              const n = t === "all" ? allCount : (counts[t] ?? 0);
              const active = t === tab;
              return (
                <Link
                  key={t}
                  href={tabHref(t)}
                  aria-current={active ? "page" : undefined}
                  className={cn(
                    "-mb-px inline-flex items-center gap-1.5 whitespace-nowrap border-b-2 px-2 py-2.5 text-xs",
                    active ? "border-accent font-medium text-text" : "border-transparent text-muted hover:text-text",
                  )}
                >
                  {TAB_LABEL[t]}
                  <span
                    className={cn(
                      "tabular rounded px-1 text-[11px]",
                      active ? "bg-accent-soft text-accent-text" : "bg-panel-2 text-muted",
                    )}
                  >
                    {num(n)}
                  </span>
                </Link>
              );
            })}
          </nav>
          {list.items.length === 0 ? (
            <EmptyState
              title={tab === "review" ? "Nothing waiting for review" : `No ${TAB_LABEL[tab].toLowerCase()} drafts`}
              description={
                tab === "review"
                  ? "New drafts arrive here when a workflow or a rep generates outreach from an account page."
                  : "Drafts appear here as they move through review."
              }
            />
          ) : (
            <ul className="max-h-[28rem] divide-y divide-border overflow-y-auto lg:max-h-[calc(100vh-16rem)]">
              {list.items.map((d) => {
                const active = selected?.id === d.id;
                const ch = CHANNEL[d.channel];
                const blocking = d.guardrails.filter((g) => !g.passed && g.blocking).length;
                const Icon = ch.icon;
                return (
                  <li key={d.id}>
                    <Link
                      href={tabHref(tab, d.id)}
                      aria-current={active ? "true" : undefined}
                      className={cn(
                        "block border-l-2 px-3 py-2.5 hover:bg-panel-2",
                        active ? "border-accent bg-accent-soft/60" : "border-transparent",
                      )}
                    >
                      <div className="flex items-center justify-between gap-2">
                        <span className="truncate text-sm font-medium text-text">{d.account_name ?? "Unknown account"}</span>
                        <span className="shrink-0 text-[11px] text-muted">{relTime(d.created_at)}</span>
                      </div>
                      <div className="mt-0.5 flex items-center gap-1.5 text-xs text-muted">
                        <Icon className="size-3.5 shrink-0" aria-hidden />
                        <span className="sr-only">{ch.label}:</span>
                        <span className="truncate">
                          {d.contact_name ?? "No contact"}
                          {d.contact_title ? ` · ${d.contact_title}` : ""}
                        </span>
                      </div>
                      <div className="mt-1 truncate text-xs text-text">
                        {d.subject ?? d.body.split("\n")[0]}
                      </div>
                      <div className="mt-1.5 flex flex-wrap items-center gap-1.5">
                        {tab === "all" && <StatusBadge status={d.status} />}
                        {blocking > 0 ? (
                          <Badge tone="danger">
                            <ShieldAlert className="size-3" aria-hidden /> {blocking} blocking
                          </Badge>
                        ) : (
                          <Badge tone="success">
                            <ShieldCheck className="size-3" aria-hidden /> Guardrails pass
                          </Badge>
                        )}
                        <span className="text-[11px] text-muted">{ch.label}</span>
                      </div>
                    </Link>
                  </li>
                );
              })}
            </ul>
          )}
        </section>

        {/* Detail */}
        <div className="min-w-0">
          {selected ? (
            <DraftDetail draft={selected} tab={tab} movedOut={movedOut} />
          ) : selectedId ? (
            <Panel>
              <EmptyState title="Draft not found" description="It may have been deleted, or the link is stale." />
            </Panel>
          ) : (
            <Panel>
              <EmptyState title="Select a draft" description="Pick a draft from the queue to review its message, reasoning and guardrails." />
            </Panel>
          )}
        </div>
      </div>
    </div>
  );
}

function DraftDetail({ draft: d, tab, movedOut }: { draft: DraftRow; tab: Tab; movedOut: boolean }) {
  const ch = CHANNEL[d.channel];
  const Icon = ch.icon;
  const blockingFails = d.guardrails.filter((g) => !g.passed && g.blocking);
  const advisoryFails = d.guardrails.filter((g) => !g.passed && !g.blocking);
  const cited = citedRefs(d);
  const chain = d.reasoning_chain;

  const steps: { key: string; label: string; content: React.ReactNode }[] = [
    {
      key: "signal",
      label: "Signal",
      content: chain.signal ? (
        <span className="flex flex-wrap items-center gap-1.5">
          <span>{chain.signal.text}</span>
          {chain.signal.ref && <RefChip ref_={chain.signal.ref} />}
          <span className="text-[11px] text-muted">{pct(chain.signal.confidence, 0)} confidence</span>
        </span>
      ) : null,
    },
    { key: "pain", label: "Pain hypothesis", content: chain.pain_hypothesis },
    { key: "value", label: "Value proposition", content: chain.value_proposition },
    {
      key: "proof",
      label: "Proof",
      content: chain.proof_source ? <span className="font-mono text-[11px]">{chain.proof_source}</span> : null,
    },
    { key: "question", label: "Question", content: chain.question },
    { key: "cta", label: "Call to action", content: chain.cta },
  ];

  return (
    <div className="space-y-4">
      {movedOut && (
        <p className="rounded-md border border-border bg-panel px-3 py-2 text-xs text-muted">
          This draft is now <StatusBadge status={d.status} /> and no longer in the {TAB_LABEL[tab].toLowerCase()} list.{" "}
          <Link href={tabHref(d.status, d.id)} className="text-accent-text hover:underline">
            Open it in {TAB_LABEL[d.status]}
          </Link>
        </p>
      )}

      <Panel
        title={
          <span className="flex flex-wrap items-center gap-2">
            <Link href={`/accounts/${d.account_id}`} className="hover:underline">
              {d.account_name ?? "Unknown account"}
            </Link>
            <StatusBadge status={d.status} />
          </span>
        }
        description={
          <span className="inline-flex flex-wrap items-center gap-x-2 gap-y-1">
            <span className="inline-flex items-center gap-1">
              <Icon className="size-3.5" aria-hidden /> {ch.label}
            </span>
            <span aria-hidden>·</span>
            <span>
              To {d.contact_name ?? "no contact"}
              {d.contact_title ? `, ${d.contact_title}` : ""}
            </span>
            <span aria-hidden>·</span>
            <span>Angle: {titleCase(d.angle)}</span>
          </span>
        }
        actions={<DemoBadge />}
      >
        <MessageCard
          key={`${d.id}:${d.version}`}
          draftId={d.id}
          channel={d.channel}
          subject={d.subject}
          body={d.body}
          status={d.status}
        />
        <dl className="mt-3 grid grid-cols-2 gap-x-4 gap-y-2 text-xs sm:grid-cols-4">
          <Meta label="Generator" value={<span className="font-mono text-[11px]">{d.generator}</span>} />
          <Meta label="Version" value={`v${d.version}`} />
          <Meta label="Created" value={<span title={dateTime(d.created_at)}>{relTime(d.created_at)}</span>} />
          <Meta
            label="Workflow run"
            value={
              d.workflow_run_id ? (
                <Link href={`/workflows/runs/${d.workflow_run_id}`} className="font-mono text-[11px] text-accent-text hover:underline">
                  {d.workflow_run_id.slice(0, 8)}
                </Link>
              ) : (
                <span className="text-muted">Manual</span>
              )
            }
          />
          {d.approved_by && <Meta label="Approved by" value={`${d.approved_by} · ${relTime(d.approved_at)}`} className="col-span-2" />}
          {d.status === "rejected" && d.rejection_reason && (
            <Meta label="Rejection reason" value={d.rejection_reason} className="col-span-2 sm:col-span-4" />
          )}
        </dl>
      </Panel>

      <Panel title="Decision" description={STATUS_HELP[d.status]}>
        <div className="flex flex-wrap items-start gap-2">
          <Actions draft={d} blocked={blockingFails.length > 0} />
        </div>
        {d.status === "review" && blockingFails.length > 0 && (
          <p className="mt-3 flex items-start gap-1.5 text-xs text-danger">
            <ShieldAlert className="mt-0.5 size-3.5 shrink-0" aria-hidden />
            Approval is blocked by {blockingFails.length === 1 ? "a failing blocking guardrail" : `${blockingFails.length} failing blocking guardrails`}:{" "}
            {blockingFails.map((g) => titleCase(g.check)).join(", ")}. Edit the message to fix it, or reject the draft.
          </p>
        )}
        <p className="mt-3 text-[11px] text-muted">
          Ready = handed off to a sequencer. GTMOS does not send email, LinkedIn messages or calls.
        </p>
      </Panel>

      <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
        <Panel
          title="Guardrails"
          description={
            blockingFails.length
              ? `${blockingFails.length} blocking failure${blockingFails.length === 1 ? "" : "s"}${advisoryFails.length ? `, ${advisoryFails.length} advisory` : ""}`
              : advisoryFails.length
                ? `All blocking checks pass · ${advisoryFails.length} advisory`
                : "All checks pass"
          }
        >
          {d.guardrails.length === 0 ? (
            <p className="text-xs text-muted">No guardrail results recorded for this draft.</p>
          ) : (
            <ul className="space-y-2.5">
              {d.guardrails.map((g) => (
                <li key={g.check} className="flex items-start gap-2 text-xs">
                  {g.passed ? (
                    <CircleCheck className="mt-0.5 size-4 shrink-0 text-success" aria-label="Passed" />
                  ) : (
                    <CircleX className={cn("mt-0.5 size-4 shrink-0", g.blocking ? "text-danger" : "text-warning")} aria-label="Failed" />
                  )}
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-1.5">
                      <span className="font-medium text-text">{titleCase(g.check)}</span>
                      {g.blocking ? (
                        <Badge tone={g.passed ? "neutral" : "danger"}>Blocking</Badge>
                      ) : (
                        <Badge>Advisory</Badge>
                      )}
                    </div>
                    <p className="mt-0.5 break-words text-muted">{g.detail}</p>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </Panel>

        <Panel title="Reasoning chain" description="Why this message, in order">
          <ol className="relative">
            {steps.map((s, i) => (
              <li key={s.key} className="relative flex gap-3 pb-4 last:pb-0">
                {i < steps.length - 1 && <span aria-hidden className="absolute left-[9px] top-5 h-[calc(100%-1rem)] w-px bg-border" />}
                <span
                  aria-hidden
                  className={cn(
                    "relative z-10 mt-0.5 grid size-[19px] shrink-0 place-items-center rounded-full border text-[10px] font-semibold",
                    s.content ? "border-accent/40 bg-accent-soft text-accent-text" : "border-border bg-panel-2 text-subtle",
                  )}
                >
                  {i + 1}
                </span>
                <div className="min-w-0 text-xs">
                  <div className="text-[11px] font-medium uppercase tracking-wide text-muted">{s.label}</div>
                  <div className="mt-0.5 text-text">{s.content || <span className="text-subtle">Not recorded</span>}</div>
                </div>
              </li>
            ))}
          </ol>
        </Panel>
      </div>

      <Panel
        title="Evidence"
        description={`${d.evidence.length} item${d.evidence.length === 1 ? "" : "s"} available to the generator · cited refs highlighted`}
        bodyClassName="p-0"
      >
        {d.evidence.length === 0 ? (
          <EmptyState title="No evidence attached" description="Drafts without evidence cannot pass the numbers-grounded check." />
        ) : (
          <ul className="divide-y divide-border">
            {d.evidence.map((e) => (
              <li key={e.ref} className={cn("flex gap-3 px-4 py-2.5 text-xs", cited.has(e.ref) && "bg-accent-soft/40")}>
                <RefChip ref_={e.ref} strong={cited.has(e.ref)} />
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-1.5">
                    <span className="font-medium text-text">{e.label}</span>
                    {cited.has(e.ref) && <Badge tone="accent">Cited</Badge>}
                  </div>
                  <p className="mt-0.5 break-words text-muted">{e.detail}</p>
                </div>
              </li>
            ))}
          </ul>
        )}
      </Panel>
    </div>
  );
}

function Actions({ draft: d, blocked }: { draft: DraftRow; blocked: boolean }) {
  const path = `/drafts/${d.id}/transition`;
  switch (d.status) {
    case "draft":
      return (
        <>
          <ActionButton path={path} body={{ target: "review" }} variant="primary">
            Submit for review
          </ActionButton>
          <ReasonTransition draftId={d.id} target="rejected" label="Reject" confirmLabel="Reject draft" placeholder="Why is this draft not worth sending?" variant="danger" />
        </>
      );
    case "review":
      return (
        <>
          <ActionButton path={path} body={{ target: "approved" }} variant="primary" disabled={blocked}>
            Approve
          </ActionButton>
          <ReasonTransition draftId={d.id} target="draft" label="Send back to draft" confirmLabel="Send back" placeholder="What needs to change?" />
          <ReasonTransition draftId={d.id} target="rejected" label="Reject" confirmLabel="Reject draft" placeholder="Why is this draft not worth sending?" variant="danger" />
        </>
      );
    case "approved":
      return (
        <>
          <ActionButton path={path} body={{ target: "ready", reason: "Handed off to sequencer" }} variant="primary" confirmLabel="Confirm hand-off">
            Mark ready for sequencer
          </ActionButton>
          <ReasonTransition draftId={d.id} target="draft" label="Back to draft" confirmLabel="Move to draft" placeholder="What needs to change?" />
        </>
      );
    case "ready":
      return (
        <ActionButton path={path} body={{ target: "draft", reason: "Pulled back from sequencer hand-off" }} confirmLabel="Confirm pull back">
          Pull back to draft
        </ActionButton>
      );
    case "rejected":
      return (
        <ActionButton path={path} body={{ target: "draft", reason: "Reopened" }}>
          Reopen as draft
        </ActionButton>
      );
  }
}

function RefChip({ ref_, strong }: { ref_: string; strong?: boolean }) {
  return (
    <span
      className={cn(
        "inline-flex h-5 shrink-0 items-center rounded border px-1 font-mono text-[10px] font-medium",
        strong ? "border-accent/40 bg-accent-soft text-accent-text" : "border-border bg-panel-2 text-muted",
      )}
    >
      {ref_}
    </span>
  );
}

function Meta({ label, value, className }: { label: string; value: React.ReactNode; className?: string }) {
  return (
    <div className={cn("min-w-0", className)}>
      <dt className="text-[11px] text-muted">{label}</dt>
      <dd className="mt-0.5 break-words text-text">{value}</dd>
    </div>
  );
}
