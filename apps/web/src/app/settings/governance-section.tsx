import { ActionButton } from "@/components/ui/action-button";
import { Badge } from "@/components/ui/badge";
import { Panel } from "@/components/ui/panel";
import { ErrorState } from "@/components/ui/states";
import { dateTime } from "@/lib/format";

export interface GovernanceSwitch {
  key: string;
  label: string;
  enabled: boolean;
  stops: string;
  use_when: string;
}

export interface GovernanceState {
  switches: GovernanceSwitch[];
  all_paused: boolean;
  any_paused: boolean;
  paused_at: string | null;
  paused_by: string | null;
  paused_reason: string | null;
}

/**
 * The stop button. Environment variables decide what GTMOS *can* do; these decide what it is doing
 * right now, which is the distinction that matters when something is going wrong and the person who
 * noticed is not an engineer.
 */
export function GovernanceSection({ governance }: { governance: GovernanceState | null }) {
  if (!governance) {
    return (
      <Panel title="Operational controls">
        <ErrorState title="Couldn't load the operational controls" />
      </Panel>
    );
  }

  return (
    <div className="space-y-4">
      <Panel
        title="Stop everything"
        description="One action that halts automation, outbound and CRM writes. Takes effect on the next action, not after a deploy."
      >
        {governance.any_paused ? (
          <div className="space-y-3">
            <div className="rounded-md border border-danger-soft bg-danger-soft/40 p-3">
              <div className="flex flex-wrap items-center gap-2">
                <Badge tone="danger">{governance.all_paused ? "Everything is paused" : "Partially paused"}</Badge>
                {governance.paused_at && <span className="text-xs text-muted">since {dateTime(governance.paused_at)}</span>}
              </div>
              {governance.paused_by && (
                <p className="mt-1.5 text-xs text-text">
                  Paused by <span className="font-medium">{governance.paused_by}</span>
                  {governance.paused_reason && <>: {governance.paused_reason}</>}
                </p>
              )}
            </div>
            <ActionButton path="/governance/resume" variant="primary" confirmLabel="Confirm resume">
              Resume everything
            </ActionButton>
          </div>
        ) : (
          <div className="space-y-3">
            <p className="text-xs text-muted">
              Everything is running. Pausing records who stopped it and why, because that is the first question asked
              afterwards.
            </p>
            <ActionButton
              path="/governance/pause"
              body={{ reason: "Paused from the settings page" }}
              variant="danger"
              confirmLabel="Confirm pause"
            >
              Pause all automation
            </ActionButton>
          </div>
        )}
      </Panel>

      <Panel
        title="Individual switches"
        description="Three rather than one, because the reasons differ · every change is audited"
        bodyClassName="p-0"
      >
        <ul className="divide-y divide-border">
          {governance.switches.map((s) => (
            <li key={s.key} className="flex flex-col gap-2 p-4 sm:flex-row sm:items-start sm:justify-between">
              <div className="min-w-0">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="text-sm font-medium text-text">{s.label}</span>
                  {s.enabled ? <Badge tone="success">Running</Badge> : <Badge tone="danger">Paused</Badge>}
                </div>
                <p className="mt-1 text-xs text-muted">{s.stops}</p>
                <p className="mt-0.5 text-[11px] text-subtle">Use when: {s.use_when}</p>
              </div>
              <ActionButton
                path="/governance/switch"
                method="PATCH"
                body={{ switch: s.key, enabled: !s.enabled, reason: `Toggled from settings` }}
                variant={s.enabled ? "danger" : "primary"}
                confirmLabel={s.enabled ? "Confirm pause" : "Confirm resume"}
                className="shrink-0"
              >
                {s.enabled ? "Pause" : "Resume"}
              </ActionButton>
            </li>
          ))}
        </ul>
        <p className="border-t border-border px-4 py-3 text-[11px] text-muted">
          A blocked request returns <span className="font-mono">423 Locked</span> with the operator&apos;s reason, so
          whoever hits it learns why rather than seeing a failure. Pausing stops actions, never data: queued work stays
          queued and resumes where it stopped.
        </p>
      </Panel>
    </div>
  );
}
