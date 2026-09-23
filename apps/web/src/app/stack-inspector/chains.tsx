import { ArrowDown, ArrowRight, Target } from "lucide-react";
import Link from "next/link";

import { EvidenceList, RawJson } from "@/components/insights/evidence";
import { Badge } from "@/components/ui/badge";
import { Panel } from "@/components/ui/panel";
import { EmptyState } from "@/components/ui/states";
import { num } from "@/lib/format";
import { cn } from "@/lib/utils";

/**
 * Causal chains: root cause → mechanism → consequence, with the account count on every link.
 *
 * The API intersects one account set through every step, so the counts only ever narrow. The display
 * has to carry that honestly — the confidence and its limits are always visible, never folded away,
 * because a flow diagram is exactly the kind of picture that can imply proof it does not have.
 */

export interface ChainLink {
  step: number;
  label: string;
  count: number;
  sentence: string;
  query: string;
  evidence: Record<string, unknown>;
}

export interface CausalChain {
  key: string;
  title: string;
  root_cause: string;
  consequence_label: string;
  links: ChainLink[];
  consequence: { label: string; accounts: number; sentence: string; metrics: Record<string, unknown> };
  fix: { title: string; how: string; expected_effect: string; rec_key: string | null };
  confidence: { level: "high" | "medium" | "low"; basis: string; statement: string; limits: string };
  accounts: { id: string; name: string; icp_score: number | null; grade: string | null; region: string | null }[];
  traced_accounts: number;
}

const CHAIN_LINK: Record<string, { href: string; label: string }> = {
  size_gap_blocks_routing: { href: "/data-quality", label: "Missing-field issues" },
  domain_gap_blocks_enrichment: { href: "/data-quality", label: "Missing-field issues" },
  provider_conflict_decides_owner: { href: "/data-quality", label: "Provider conflicts" },
  territory_gap_strands_accounts: { href: "/routing", label: "Routing rules" },
};

const CONFIDENCE_TONE = { high: "info", medium: "warning", low: "neutral" } as const;

function LinkRow({ link, last }: { link: ChainLink; last: boolean }) {
  const hasEvidence = Object.keys(link.evidence).length > 0;
  return (
    <li className="relative grid grid-cols-[2.5rem_1fr] gap-3">
      {!last && <span aria-hidden className="absolute bottom-0 left-5 top-10 w-px -translate-x-1/2 bg-border" />}
      <span
        className={cn(
          "tabular z-10 grid size-10 place-items-center rounded-full border text-xs font-semibold",
          last ? "border-danger/40 bg-danger-soft text-danger" : "border-border bg-panel-2 text-text",
        )}
      >
        {num(link.count)}
      </span>
      <div className={cn("min-w-0", last ? "pb-1" : "pb-5")}>
        <p className="text-[11px] font-semibold uppercase tracking-wide text-muted">
          <span className="tabular text-subtle">{link.step}. </span>
          {link.label}
        </p>
        <p className="mt-0.5 text-sm text-text">{link.sentence}</p>
        <details className="mt-1.5 text-xs">
          <summary className="cursor-pointer select-none text-muted hover:text-text">Query behind this count</summary>
          <div className="mt-1.5 space-y-2 rounded-md border border-border bg-panel-2/50 p-2.5">
            <code className="block break-words font-mono text-[11px] text-muted">{link.query}</code>
            {hasEvidence && <EvidenceList evidence={link.evidence} nested />}
          </div>
        </details>
      </div>
    </li>
  );
}

function ChainCard({ chain }: { chain: CausalChain }) {
  const jump = CHAIN_LINK[chain.key];
  const correlational = chain.confidence.basis.includes("correlation");
  return (
    <Panel
      id={`chain-${chain.key}`}
      className="scroll-mt-6"
      title={<span className="break-words">{chain.title}</span>}
      description={`${num(chain.traced_accounts)} accounts traced through all ${chain.links.length} links`}
      actions={
        <Badge tone={CONFIDENCE_TONE[chain.confidence.level] ?? "neutral"} title={chain.confidence.statement}>
          {chain.confidence.level} confidence
        </Badge>
      }
    >
      <ol className="mb-1">
        {chain.links.map((l, i) => (
          <LinkRow key={l.step} link={l} last={i === chain.links.length - 1} />
        ))}
      </ol>

      <div className="mt-3 rounded-lg border border-danger/30 bg-danger-soft p-3">
        <div className="flex items-start gap-2">
          <ArrowDown className="mt-0.5 size-4 shrink-0 text-danger" aria-hidden />
          <div className="min-w-0">
            <p className="text-[11px] font-semibold uppercase tracking-wide text-danger">{chain.consequence.label}</p>
            <p className="mt-0.5 text-sm text-text">{chain.consequence.sentence}</p>
          </div>
        </div>
        <div className="mt-2.5 rounded-md border border-border bg-panel/70 p-2.5">
          <EvidenceList evidence={chain.consequence.metrics} nested />
        </div>
      </div>

      <div className="mt-3 grid gap-3 sm:grid-cols-2">
        <div className="rounded-md border border-border bg-panel-2/40 p-3">
          <p className="flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wide text-muted">
            <Target className="size-3.5" aria-hidden />
            Fix
          </p>
          <p className="mt-1 text-sm font-medium text-text">{chain.fix.title}</p>
          <p className="mt-1 text-xs text-muted">{chain.fix.how}</p>
          <p className="mt-1.5 text-xs text-text">
            <span className="font-medium text-muted">Expected effect: </span>
            {chain.fix.expected_effect}
          </p>
        </div>
        <div className="rounded-md border border-border bg-panel-2/40 p-3">
          <p className="flex flex-wrap items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wide text-muted">
            How sure is this
            <Badge tone={correlational ? "warning" : "neutral"}>{chain.confidence.basis}</Badge>
          </p>
          <p className="mt-1 text-xs text-text">{chain.confidence.statement}</p>
          <p className="mt-1.5 text-xs text-muted">
            <span className="font-medium text-warning">What it does not prove: </span>
            {chain.confidence.limits}
          </p>
        </div>
      </div>

      {chain.accounts.length > 0 && (
        <div className="mt-3 flex flex-wrap items-center gap-1.5">
          <span className="text-[11px] text-muted">Accounts at the end of this chain:</span>
          {chain.accounts.map((a) => (
            <Badge key={a.id} className="max-w-[12rem]" title={`${a.region ?? "no region"} · ICP ${a.icp_score ?? "—"}`}>
              <span className="truncate">{a.name}</span>
            </Badge>
          ))}
        </div>
      )}

      <div className="mt-3 flex items-center justify-between gap-3">
        <RawJson value={chain} />
        {jump && (
          <Link
            href={jump.href}
            className="inline-flex shrink-0 items-center gap-1 text-xs text-accent-text hover:underline"
          >
            {jump.label}
            <ArrowRight className="size-3" aria-hidden />
          </Link>
        )}
      </div>
    </Panel>
  );
}

export function CausalChains({ chains }: { chains: CausalChain[] }) {
  return (
    <section aria-labelledby="chains-heading" className="space-y-3">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 id="chains-heading" className="text-sm font-semibold text-text">
          Causal chains
        </h2>
        <span className="max-w-xl text-[11px] text-muted">
          Each link intersects the accounts from the link above it, so a chain counts the same accounts end to end
          rather than three findings that merely sound related.
        </span>
      </div>
      {chains.length ? (
        <div className="space-y-4">
          {chains.map((c) => (
            <ChainCard key={c.key} chain={c} />
          ))}
        </div>
      ) : (
        <Panel bodyClassName="p-0">
          <EmptyState
            title="No chain survives its own test today"
            description="A chain is only shown when the same accounts appear at every step, from root cause to consequence. Nothing in the current data carries through end to end."
          />
        </Panel>
      )}
    </section>
  );
}
