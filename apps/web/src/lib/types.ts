/* API payload types (kept in sync with apps/api/src/gtmos/api/routes). */

export type Grade = "A" | "B" | "C" | "D" | "X";
export type DataOrigin = "demo" | "live";

export interface Workspace {
  id: string;
  name: string;
  seller_name: string;
  seller_product: string;
  mode: "demo" | "live";
  demo_anchor_at: string | null;
  llm_mode: "demo" | "live";
  hubspot_mode: "demo" | "live";
  counts: { accounts: number; contacts: number; signals: number; opportunities: number };
  flagship_account_id: string;
}

export interface Categories {
  fit: number;
  intent: number;
  timing: number;
  technical: number;
  engagement: number;
}

export interface AccountRow {
  id: string;
  name: string;
  domain: string | null;
  industry: string | null;
  employee_count: number | null;
  segment: string | null;
  region: string | null;
  country: string | null;
  icp_score: number | null;
  score_grade: Grade | null;
  intent_score: number | null;
  categories: Categories | null;
  funnel_stage: string;
  is_customer: boolean;
  owner: string | null;
  last_signal: { title: string; type: string } | null;
  last_signal_at: string | null;
  data_origin: DataOrigin;
  is_flagship: boolean;
}

export interface Paged<T> {
  items: T[];
  total: number;
  page: number;
  page_size: number;
}

export interface ScoreComponent {
  id: string;
  category: keyof Categories;
  key: string;
  label: string;
  points: number;
  max_points: number;
  explanation: string;
  evidence: Record<string, unknown>[];
}

export interface Signal {
  id: string;
  account_id: string;
  contact_id: string | null;
  signal_type: string;
  observed_at: string;
  ingested_at: string;
  source: string;
  source_url: string | null;
  confidence: number;
  strength: number;
  title: string;
  explanation: string;
  evidence: Record<string, unknown>;
  data_origin: DataOrigin;
  account_name?: string;
  account_score?: number | null;
  account_grade?: Grade | null;
  account_domain?: string | null;
  category?: string | null;
}

export interface Contact {
  id: string;
  account_id: string | null;
  first_name: string | null;
  last_name: string | null;
  full_name: string;
  email: string | null;
  email_status: string;
  title: string | null;
  seniority: string | null;
  department: string | null;
  lifecycle_stage: string;
  do_not_contact: boolean;
  roles: string[];
  data_origin: DataOrigin;
  account_name?: string | null;
  source: string;
}

export interface CommitteeRole {
  id: string;
  contact_id: string;
  role: string;
  role_label: string;
  rank: number;
  score: number;
  confidence: number;
  rationale: string[];
  is_manual_override: boolean;
  overridden_by: string | null;
  contact: { id: string; name: string; title: string | null; email: string | null; email_status: string } | null;
}

export interface Claim {
  text: string;
  evidence: string[];
  hypothesis: boolean;
}

export interface Evidence {
  id: string;
  ref: string;
  kind: string;
  label: string;
  detail: string;
  source: string;
  source_url: string | null;
  source_record_type: string | null;
  source_record_id: string | null;
  observed_at: string | null;
  confidence: number;
}

export interface ResearchReport {
  id: string;
  account_id: string;
  status: string;
  generator: string;
  prompt_version: string;
  sections: Record<string, Claim[]> & { _meta?: { angle?: string; llm_fallback_reason?: string } };
  unsupported_claims: { section: string; text: string; reason: string }[];
  created_at: string;
  created_by: string;
  latency_ms: number;
  evidence: Evidence[];
}

export interface Guardrail {
  check: string;
  passed: boolean;
  blocking: boolean;
  detail: string;
}

export interface Draft {
  id: string;
  account_id: string;
  contact_id: string | null;
  channel: "email" | "linkedin" | "call_prep";
  subject: string | null;
  body: string;
  angle: string;
  reasoning_chain: {
    signal?: { text: string; ref: string | null; confidence: number } | null;
    pain_hypothesis?: string;
    value_proposition?: string;
    proof_source?: string;
    question?: string;
    cta?: string;
  };
  evidence: { ref: string; label: string; detail: string }[];
  guardrails: Guardrail[];
  status: "draft" | "review" | "approved" | "ready" | "rejected";
  generator: string;
  version: number;
  approved_by: string | null;
  approved_at: string | null;
  created_at: string;
  workflow_run_id: string | null;
  account_name?: string;
  account_score?: number | null;
  contact_name?: string | null;
  contact_title?: string | null;
}

export interface Activity {
  id: string;
  account_id: string | null;
  contact_id: string | null;
  type: string;
  channel: string | null;
  occurred_at: string;
  subject: string | null;
  summary: string | null;
  status: string | null;
  campaign?: string | null;
  contact_name?: string | null;
  account_name?: string | null;
  data_origin: DataOrigin;
  source: string;
  properties: Record<string, unknown>;
}

export interface Opportunity {
  id: string;
  account_id: string;
  name: string;
  stage: string;
  amount_usd: number;
  opened_at: string;
  expected_close_date: string | null;
  closed_at: string | null;
  lead_source: string | null;
  lost_reason: string | null;
  owner?: string | null;
  campaign?: string | null;
  account_name?: string;
  account_grade?: Grade | null;
  data_origin: DataOrigin;
}

export interface WorkflowRunSummary {
  id: string;
  workflow_id: string;
  account_id: string | null;
  status: string;
  error: string | null;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  correlation_id: string;
  attempt: number;
  workflow?: string;
  workflow_key?: string;
  account_name?: string | null;
  synthetic_history?: boolean;
  trigger?: string;
  data_origin: DataOrigin;
  condition_results?: { condition: string; passed: boolean; actual: unknown }[];
}

export interface StepRun {
  id: string;
  step_key: string;
  position: number;
  action: string;
  status: string;
  attempts: number;
  max_attempts: number;
  input: Record<string, unknown>;
  output: Record<string, unknown>;
  error: string | null;
  logs: { at?: string; level: string; msg: string }[];
  started_at: string | null;
  finished_at: string | null;
  duration_ms: number | null;
}

export interface RoutingDecision {
  id: string;
  account_id: string;
  outcome: string;
  assigned_to: string | null;
  matched_rules: { rule: string; name: string; priority: number }[];
  conflicts: { rule: string; name: string; destination: string; lost_because: string }[];
  explanation: string[];
  trigger: string;
  latency_ms: number | null;
  decided_at: string;
  account_name?: string;
  rule_name?: string | null;
  region?: string | null;
  segment?: string | null;
}

export interface EnrichmentAttempt {
  id: string;
  field: string;
  provider: string;
  position: number;
  outcome: string;
  value: unknown;
  confidence: number | null;
  latency_ms: number;
  cost_credits: number;
  error: string | null;
}

export interface AccountDetail {
  account: Record<string, unknown> & {
    id: string;
    name: string;
    domain: string | null;
    description: string | null;
    industry: string | null;
    employee_count: number | null;
    employee_growth_12m: number | null;
    country: string | null;
    region: string | null;
    city: string | null;
    funding_stage: string | null;
    total_funding_usd: number | null;
    technologies: string[];
    ai_team_size: number | null;
    ai_open_roles: number | null;
    segment: string | null;
    funnel_stage: string;
    lifecycle_stage: string;
    is_customer: boolean;
    owner: string | null;
    icp_score: number | null;
    score_grade: Grade | null;
    intent_score: number | null;
    data_origin: DataOrigin;
    is_flagship: boolean;
    last_enriched_at: string | null;
    hubspot_company_id: string | null;
    source: string;
  };
  provenance: Record<string, { source: string; confidence: number; observed_at: string; is_manual_lock: boolean }>;
  score:
    | (Categories & {
        id: string;
        total: number;
        grade: Grade;
        excluded: boolean;
        exclusion_reason: string | null;
        summary: string;
        computed_at: string;
        icp_version: number;
        inputs_hash: string;
        trigger: string;
        components: ScoreComponent[];
      })
    | null;
  score_history: { total: number; computed_at: string; trigger: string }[];
  signals: Signal[];
  contacts: Contact[];
  committee: CommitteeRole[];
  research: ResearchReport | null;
  drafts: Draft[];
  activities: Activity[];
  opportunities: Opportunity[];
  workflow_runs: WorkflowRunSummary[];
  routing_decisions: RoutingDecision[];
  enrichment: { runs: Record<string, unknown>[]; latest_attempts: EnrichmentAttempt[] };
  stage_history: { id: string; from_stage: string | null; to_stage: string; changed_at: string; changed_by: string; reason: string | null }[];
  audit: AuditEvent[];
  crm_sync: { external_id: string | null; last_synced_at: string | null; is_simulated: boolean; last_payload: Record<string, unknown> } | null;
  next_action: { key: string; label: string; reason: string; priority: number };
}

export interface AuditEvent {
  id: string;
  actor_type: string;
  actor: string;
  action: string;
  entity_type: string;
  entity_id: string | null;
  before: Record<string, unknown> | null;
  after: Record<string, unknown> | null;
  reason: string | null;
  correlation_id: string | null;
  occurred_at: string;
}

export interface Overview {
  window_days: number;
  accounts_sourced: number;
  icp_accounts: number;
  grade_distribution: Record<string, number>;
  high_intent_accounts: number;
  enrichment_coverage: number;
  contacts: number;
  contacts_verified: number;
  contact_coverage: number;
  messages_drafted: number;
  messages_in_review: number;
  messages_approved: number;
  emails_sent: number;
  emails_delivered: number;
  emails_opened: number;
  replies: number;
  positive_replies: number;
  reply_rate: number;
  meetings: number;
  qualified_accounts: number;
  opportunities_created: number;
  pipeline_created: number;
  won_deals: number;
  won_revenue: number;
  open_opportunities: number;
  open_pipeline: number;
  open_rate_caveat: string;
}

export interface Funnel {
  window_days: number;
  stages: { stage: string; accounts: number; conversion_from_previous: number | null }[];
  lost: number;
}

export interface BreakdownRow {
  key: string;
  contacted: number;
  engaged: number;
  meetings: number;
  opportunities: number;
  pipeline: number;
  won: number;
  engagement_rate: number;
  meeting_rate: number;
  opportunity_rate: number;
  low_sample: boolean;
}

export interface Breakdown {
  dimension: string;
  window_days: number;
  rows: BreakdownRow[];
}

export interface PipelineTrend {
  weeks: { week: string; opportunities: number; pipeline: number; won: number; meetings: number }[];
  note: string;
}

export type HealthStatus = "healthy" | "warning" | "critical";

export interface InspectorSection {
  key: string;
  title: string;
  status: HealthStatus;
  headline: string;
  simulated?: boolean;
  evidence: Record<string, unknown>;
}

export interface Recommendation {
  key: string;
  rank: number;
  title: string;
  why: string;
  how: string;
  impact_accounts: number;
  priority_accounts: number;
  evidence: Record<string, unknown>;
}

export interface Inspector {
  generated_at: string;
  overall_status: HealthStatus;
  summary: Record<HealthStatus, number>;
  sections: InspectorSection[];
  recommendations: Recommendation[];
  context: { stuck_accounts: number; stuck_by_stage: Record<string, number>; open_opportunities: number };
  method: string;
}
