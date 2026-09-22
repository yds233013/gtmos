/* Payload types for the insight pages (campaigns, experiments, copilot, scoring, settings).
   Kept here rather than in @/lib/types so these pages can evolve independently. */

import type { AuditEvent, BreakdownRow, DataOrigin } from "@/lib/types";

// Campaigns ------------------------------------------------------------------------------------

export interface CampaignMetrics {
  accounts_touched: number;
  sent: number;
  delivered: number;
  opened: number;
  bounced: number;
  replied: number;
  positive_replies: number;
  meetings: number;
  attended: number;
  opportunities: number;
  pipeline: number;
  won: number;
  won_revenue: number;
  reply_rate: number;
  positive_reply_rate: number;
}

export interface Campaign {
  id: string;
  key: string;
  name: string;
  status: string;
  hypothesis: string | null;
  target_segment: Record<string, unknown> | null;
  persona: string | null;
  trigger_signal: string | null;
  channel: string | null;
  value_prop: string | null;
  start_date: string | null;
  end_date: string | null;
  data_origin: DataOrigin;
  metrics: CampaignMetrics;
}

export interface BreakdownResponse {
  dimension: string;
  window_days: number;
  rows: BreakdownRow[];
}

// Experiments ----------------------------------------------------------------------------------

export type Verdict =
  | "insufficient_sample"
  | "insufficient_events"
  | "no_significant_difference"
  | "treatment_better"
  | "control_better";

export interface ExperimentRow {
  id: string;
  key: string;
  name: string;
  status: string;
  primary_metric: string;
  verdict: Verdict | string | null;
  campaign: string | null;
  started_at: string | null;
  ended_at: string | null;
  unit: string;
  units: number;
  data_origin: DataOrigin;
}

export interface MetricResult {
  key: string;
  n: number;
  successes: number;
  rate: number;
  ci_low: number;
  ci_high: number;
}

export interface Variant {
  key: string;
  name: string;
  description: string;
  is_control: boolean;
  units: number;
  metrics: Record<string, MetricResult>;
  pipeline: number;
}

export interface Comparison {
  absolute_lift: number | null;
  relative_lift: number | null;
  diff_ci_low: number | null;
  diff_ci_high: number | null;
  z: number | null;
  p_value: number | null;
  verdict: Verdict | string;
  explanation: string;
  required_n_per_variant: number | null;
}

export interface ExperimentDetail {
  id: string;
  key: string;
  name: string;
  hypothesis: string;
  null_hypothesis: string;
  primary_metric: string;
  unit: string;
  status: string;
  min_sample_per_variant: number;
  assignment: string;
  started_at: string | null;
  ended_at: string | null;
  campaign: string | null;
  data_origin?: DataOrigin;
  variants: Variant[];
  comparisons: Record<string, Record<string, Comparison>>;
  verdict: Verdict | string;
  verdict_explanation: string;
}

// Copilot --------------------------------------------------------------------------------------

export interface CopilotAnswer {
  question: string;
  intent: string;
  confidence: number;
  params: Record<string, unknown>;
  plan: string[];
  queries: { metric: string; params: Record<string, unknown> }[];
  answer: string;
  data: unknown;
  generator: string;
  guardrails: string[];
  suggested: string[];
}

// ICP & scoring --------------------------------------------------------------------------------

export interface Weights {
  fit: number;
  intent: number;
  timing: number;
  technical: number;
  engagement: number;
}

export interface ICPDefinition {
  name: string;
  description: string;
  core_industries: string[];
  adjacent_industries: string[];
  size: {
    min_employees: number;
    max_employees: number;
    sweet_spot_min: number;
    sweet_spot_max: number;
    hard_min_employees: number;
  };
  primary_regions: string[];
  secondary_regions: string[];
  funding_stages: string[];
  min_growth_rate: number;
  technical: { ai_team_min: number; ai_team_strong: number; llm_stack: string[]; platform_stack: string[] };
  buyer_personas: string[];
  positive_signals: Record<string, number>;
  excluded_industries: string[];
  excluded_countries: string[];
  excluded_domains: string[];
  weights: Weights;
}

export interface SignalType {
  key: string;
  name: string;
  category: string;
  default_strength: number;
  half_life_days: number;
  description: string;
}

export interface ICPResponse {
  id: string;
  version: number;
  definition: ICPDefinition;
  versions: { version: number; created_at: string; created_by: string; is_active: boolean }[];
  signal_types: SignalType[];
}

export interface ICPPreview {
  accounts_scored: number;
  grade_distribution: Record<string, number>;
  current_distribution: Record<string, number>;
  biggest_movers: { account_id: string; name: string; from: number; to: number; delta: number }[];
}

// Settings -------------------------------------------------------------------------------------

export interface Integration {
  id: string;
  provider: string;
  display_name: string;
  category: string;
  mode: "demo" | "live" | "disabled" | string;
  status: string;
  config: Record<string, unknown>;
  last_success_at: string | null;
  last_error_at: string | null;
  last_error: string | null;
}

export interface HubspotProperty {
  name: string;
  label: string;
  type: string;
  fieldType?: string;
  hasUniqueValue?: boolean;
}

export interface HubspotMapping {
  id_properties: Record<string, string>;
  custom_properties: Record<string, HubspotProperty[]>;
  objects: Record<string, string>;
}

export interface ReverseEtlPreview {
  considered: number;
  would_create: number;
  would_update: number;
  unchanged: number;
  changed_field_counts: Record<string, number>;
  sample: {
    account_id: string;
    name: string;
    is_new: boolean;
    changed_fields: string[];
    properties: Record<string, unknown>;
  }[];
  last_run: { id: string; status: string; finished_at: string | null; is_simulated: boolean } | null;
  destination_mode: string;
}

export interface SimulatedObjects {
  simulated: boolean;
  counts: Record<string, number>;
  items: {
    id: string;
    object_type: string;
    external_id: string;
    unique_key: string;
    properties: Record<string, unknown>;
    updated_at: string;
  }[];
  note: string;
}

export interface AuditResponse {
  items: AuditEvent[];
  actions: Record<string, number>;
}
