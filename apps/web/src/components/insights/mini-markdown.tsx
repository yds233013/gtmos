import { Fragment } from "react";

import { cn } from "@/lib/utils";

/**
 * A deliberately tiny, safe Markdown subset → React elements (never HTML strings).
 * Supports: **bold**, `code`, "- " bullet lines, "1. " numbered lines, and paragraphs.
 */

type Block =
  | { kind: "p"; text: string }
  | { kind: "ul"; items: string[] }
  | { kind: "ol"; items: string[]; start: number };

export function parseBlocks(source: string): Block[] {
  const blocks: Block[] = [];
  for (const raw of source.split(/\r?\n/)) {
    const line = raw.trimEnd();
    if (!line.trim()) continue;
    const bullet = line.match(/^\s*[-*]\s+(.*)$/);
    const numbered = line.match(/^\s*(\d+)[.)]\s+(.*)$/);
    const last = blocks[blocks.length - 1];
    if (bullet) {
      if (last?.kind === "ul") last.items.push(bullet[1]);
      else blocks.push({ kind: "ul", items: [bullet[1]] });
    } else if (numbered) {
      if (last?.kind === "ol") last.items.push(numbered[2]);
      else blocks.push({ kind: "ol", items: [numbered[2]], start: Number(numbered[1]) || 1 });
    } else {
      blocks.push({ kind: "p", text: line.trim() });
    }
  }
  return blocks;
}

export function renderInline(text: string): React.ReactNode[] {
  const out: React.ReactNode[] = [];
  const re = /(\*\*([^*]+)\*\*|`([^`]+)`)/g;
  let last = 0;
  let m: RegExpExecArray | null;
  let i = 0;
  while ((m = re.exec(text)) !== null) {
    if (m.index > last) out.push(<Fragment key={i++}>{text.slice(last, m.index)}</Fragment>);
    if (m[2] !== undefined) {
      out.push(
        <strong key={i++} className="font-semibold text-text">
          {m[2]}
        </strong>,
      );
    } else if (m[3] !== undefined) {
      out.push(
        <code key={i++} className="rounded bg-panel-2 px-1 py-px font-mono text-[0.92em] text-text">
          {m[3]}
        </code>,
      );
    }
    last = m.index + m[0].length;
  }
  if (last < text.length) out.push(<Fragment key={i++}>{text.slice(last)}</Fragment>);
  return out;
}

export function MiniMarkdown({ source, className }: { source: string; className?: string }) {
  const blocks = parseBlocks(source);
  return (
    <div className={cn("space-y-2 text-sm leading-relaxed text-text", className)}>
      {blocks.map((b, i) => {
        if (b.kind === "p") return <p key={i}>{renderInline(b.text)}</p>;
        if (b.kind === "ul")
          return (
            <ul key={i} className="list-disc space-y-1 pl-5 marker:text-subtle">
              {b.items.map((it, j) => (
                <li key={j}>{renderInline(it)}</li>
              ))}
            </ul>
          );
        return (
          <ol key={i} start={b.start} className="list-decimal space-y-1 pl-5 marker:text-muted">
            {b.items.map((it, j) => (
              <li key={j}>{renderInline(it)}</li>
            ))}
          </ol>
        );
      })}
    </div>
  );
}
