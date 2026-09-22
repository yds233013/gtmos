import type { Workspace } from "@/lib/types";

/** Persistent, unmissable statement of what is simulated and what is live. */
export function ModeBanner({ ws }: { ws: Workspace | null }) {
  if (!ws) {
    return (
      <div className="border-b border-danger/30 bg-danger-soft px-4 py-1.5 text-xs text-danger">
        API unavailable. Start the backend (<code className="font-mono">make dev</code>) to load data.
      </div>
    );
  }
  const parts = [
    ws.mode === "demo" ? "Synthetic demo data" : "Live workspace",
    `CRM ${ws.hubspot_mode === "live" ? "live (HubSpot)" : "simulated"}`,
    `AI ${ws.llm_mode === "live" ? "live (Claude)" : "deterministic demo mode"}`,
    "No external messages are ever sent",
  ];
  return (
    <div className="flex flex-wrap items-center gap-x-3 gap-y-1 border-b border-warning/30 bg-warning-soft px-4 py-1.5 text-xs text-warning lg:px-8">
      <span className="rounded bg-warning px-1.5 py-px text-[10px] font-bold tracking-wide text-white">
        {ws.mode === "demo" ? "DEMO" : "LIVE"}
      </span>
      {parts.map((p) => (
        <span key={p} className="text-warning/90">
          {p}
        </span>
      ))}
    </div>
  );
}
