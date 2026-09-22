import { Panel } from "@/components/ui/panel";
import type { MetricDefinition } from "@/lib/types";

const CATEGORY_LABEL: Record<string, string> = {
  funnel: "Funnel",
  outbound: "Outbound",
  pipeline: "Pipeline",
  data: "Data",
  experiment: "Experiment",
};

/**
 * The metric dictionary, served from the API so the UI and the docs can never drift from the code that
 * computes the numbers.
 */
export function MetricDefinitions({ metrics }: { metrics: MetricDefinition[] }) {
  if (!metrics.length) return null;
  const categories = [...new Set(metrics.map((m) => m.category))];
  return (
    <Panel
      title="How these metrics are defined"
      description="Denominators, formulas and the caveat that stops each number being misread"
      bodyClassName="p-0"
    >
      <details className="group">
        <summary className="cursor-pointer list-none px-4 py-2.5 text-xs text-accent-text hover:bg-panel-2">
          Show {metrics.length} definitions
          <span className="ml-1 text-subtle group-open:hidden">▸</span>
          <span className="ml-1 hidden text-subtle group-open:inline">▾</span>
        </summary>
        <div className="border-t border-border">
          {categories.map((cat) => (
            <section key={cat}>
              <h3 className="bg-panel-2 px-4 py-1 text-[10px] font-medium uppercase tracking-wide text-muted">
                {CATEGORY_LABEL[cat] ?? cat}
              </h3>
              <dl className="divide-y divide-border">
                {metrics
                  .filter((m) => m.category === cat)
                  .map((m) => (
                    <div key={m.key} className="grid gap-1 px-4 py-2.5 sm:grid-cols-[200px_1fr]">
                      <dt className="text-xs font-medium text-text">{m.label}</dt>
                      <dd className="min-w-0 text-xs text-muted">
                        <p>{m.definition}</p>
                        <p className="mt-1 font-mono text-[11px] text-subtle">
                          {m.formula} · denominator: {m.denominator}
                        </p>
                        {m.caveat && <p className="mt-1 text-[11px] text-warning">Caveat: {m.caveat}</p>}
                      </dd>
                    </div>
                  ))}
              </dl>
            </section>
          ))}
        </div>
      </details>
    </Panel>
  );
}
