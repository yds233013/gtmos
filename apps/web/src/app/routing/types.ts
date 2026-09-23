import type { Condition } from "@/components/systems/conditions";

export interface RoutingRuleItem {
  id: string;
  key: string;
  name: string;
  description: string | null;
  priority: number;
  conditions: Condition[];
  assign_strategy: "user" | "pool_least_loaded" | "round_robin";
  assign_user: string | null;
  assign_team: string | null;
  overrides_existing_owner: boolean;
  is_active: boolean;
  decisions_90d: number;
  sla_hours: number | null;
  is_fallback: boolean;
}

export interface EvaluatedCondition {
  condition: string;
  field: string;
  op: string;
  expected: unknown;
  actual: unknown;
  passed: boolean;
}

export interface MatchedRule {
  rule: string;
  name: string;
  priority: number;
  conditions?: EvaluatedCondition[];
}

export interface RoutingConflict {
  rule: string;
  name: string;
  destination: string;
  lost_because: string;
  is_conflict?: boolean;
}

export type RoutingOutcome = "assigned" | "kept_owner" | "named_account" | "fallback_queue" | "unmatched";

export interface DecisionItem {
  id: string;
  account_id: string;
  account_name: string;
  region: string | null;
  segment: string | null;
  outcome: RoutingOutcome;
  assigned_to: string | null;
  rule_name: string | null;
  matched_rules: MatchedRule[];
  conflicts: RoutingConflict[];
  explanation: string[];
  trigger: string;
  latency_ms: number | null;
  decided_at: string;
}

export interface DecisionList {
  items: DecisionItem[];
  counts: Partial<Record<RoutingOutcome, number>>;
}

export interface SimulationInput {
  segment: "strategic" | "enterprise" | "mid_market" | "smb" | null;
  region: "NA" | "EMEA" | "APAC" | "LATAM" | null;
  icp_score: number;
  intent_score: number;
  is_customer: boolean;
  owner_id?: string | null;
}

export interface SimulationResult {
  outcome: RoutingOutcome;
  rule: string | null;
  assigned_to: string | null;
  explanation: string[];
  conflicts: RoutingConflict[];
  matched: MatchedRule[];
}

export interface TeamUser {
  user_id: string;
  name: string;
  team: string | null;
  capacity: number;
  is_active: boolean;
  open_accounts: number;
  utilization: number | null;
}


export interface SlaByRule {
  rule: string;
  n: number;
  met: number;
  late: number;
  untouched: number;
  pending: number;
}

export interface SlaReport {
  window_days: number;
  decisions_with_sla: number;
  met: number;
  late: number;
  untouched: number;
  pending: number;
  hit_rate: number | null;
  median_hours_to_first_touch: number | null;
  by_rule: SlaByRule[];
  worst: { account: string | null; account_id: string; state: "late" | "untouched"; overdue_hours: number }[];
  definition?: string;
  note?: string;
}
