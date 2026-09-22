export interface OpsAttentionRun {
  run_id: string;
  workflow: string;
  status: string;
  error: string | null;
  created_at: string;
  account_id: string | null;
  correlation_id: string;
}

export interface OpsSyncRun {
  id: string;
  job: string;
  status: string;
  started_at: string;
  duration_ms: number | null;
  changed: number;
  failed: number;
  skipped: number;
  retries: number;
  is_simulated: boolean;
  trigger: string;
  correlation_id: string | null;
  error: string | null;
}

export interface OpsWebhookAttention {
  id: string;
  source: string;
  status: string;
  error: string | null;
  received_at: string;
  attempts: number;
  correlation_id: string | null;
}

export interface OpsProvider {
  provider: string;
  name: string;
  attempts: number;
  hit: number;
  miss: number;
  low_confidence: number;
  error: number;
  skipped?: number;
  hit_rate: number | null;
  error_rate: number | null;
  avg_latency_ms: number | null;
  cost_credits: number;
  status: string;
}

export interface Operations {
  workflows: {
    window_days: number;
    by_status: Record<string, number>;
    executed: number;
    failure_rate: number | null;
    median_duration_ms: number | null;
    retried_steps: number;
    dead_letter_total: number;
    needs_attention: OpsAttentionRun[];
  };
  syncs: {
    window_days?: number;
    runs: number;
    failed_runs: number;
    partial_runs: number;
    records_changed: number;
    records_failed: number;
    record_failure_rate: number | null;
    retries: number;
    last_success_at: string | null;
    hours_since_success: number | null;
    all_simulated: boolean;
    recent: OpsSyncRun[];
  };
  webhooks: {
    window_days?: number;
    total: number;
    by_source: Record<string, Record<string, number>>;
    duplicates_absorbed: number;
    failure_rate: number | null;
    p50_processing_ms: number | null;
    p95_processing_ms: number | null;
    last_received: Record<string, string>;
    needs_attention: OpsWebhookAttention[];
  };
  providers: OpsProvider[];
  routing: {
    decisions_with_signal: number;
    median_signal_to_owner_hours: number | null;
    p90_signal_to_owner_hours: number | null;
    note: string;
  };
  queue: { backend: string; redis_configured: boolean };
  llm: { mode: string; model: string | null };
}

export interface WebhookEvent {
  id: string;
  source: string;
  status: string;
  payload: Record<string, unknown> | null;
}

export interface ReverseEtlPreview {
  considered: number;
  would_create: number;
  would_update: number;
  unchanged: number;
  changed_field_counts: Record<string, number>;
  last_run: { id: string; status: string; finished_at: string | null; is_simulated: boolean } | null;
  destination_mode: string;
}
