import type { Condition } from "@/components/systems/conditions";
import type { DataOrigin } from "@/lib/types";

export type RunStatus = "queued" | "running" | "succeeded" | "failed" | "skipped" | "dead_letter";

export interface WorkflowStepSpec {
  key: string;
  action: string;
  params?: Record<string, unknown>;
  max_attempts?: number;
  continue_on_failure?: boolean;
}

export interface WorkflowDefinition {
  trigger: { type: string; filters?: Condition[] };
  conditions?: Condition[];
  steps: WorkflowStepSpec[];
}

export interface WorkflowItem {
  id: string;
  key: string;
  name: string;
  description: string | null;
  trigger_type: string;
  definition: WorkflowDefinition;
  is_enabled: boolean;
  version: number;
  runs_30d: Partial<Record<RunStatus, number>>;
  last_run_at: string | null;
}

export interface ConditionResult {
  condition: string;
  passed: boolean;
  actual?: unknown;
  expected?: unknown;
  field?: string;
  op?: string;
}

export interface RunRow {
  id: string;
  workflow: string;
  workflow_key: string;
  account_id: string | null;
  account_name: string | null;
  status: RunStatus;
  error: string | null;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  correlation_id: string;
  attempt: number;
  synthetic_history: boolean;
  condition_results: ConditionResult[] | null;
  data_origin: DataOrigin;
  idempotency_key?: string;
  trigger_event?: Record<string, unknown> | null;
}

export interface RunList {
  items: RunRow[];
  counts: Partial<Record<RunStatus, number>>;
}

export interface StepLog {
  level: string;
  msg: string;
  at?: string;
}

export interface StepRunDetail {
  id: string;
  step_key: string;
  position: number;
  action: string;
  status: string;
  attempts: number;
  max_attempts: number;
  input: Record<string, unknown> | null;
  output: Record<string, unknown> | null;
  error: string | null;
  logs: StepLog[] | null;
  started_at: string | null;
  finished_at: string | null;
  duration_ms: number | null;
}

export interface RunDetail extends Omit<RunRow, "workflow"> {
  workflow_version?: number;
  idempotency_key: string;
  trigger_event: Record<string, unknown> | null;
  workflow: (Omit<WorkflowItem, "runs_30d" | "last_run_at"> & { description: string | null }) | null;
  account: { id: string; name: string } | null;
  steps: StepRunDetail[];
}
