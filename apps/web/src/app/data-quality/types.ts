export type Severity = "high" | "medium" | "low";
export type IssueStatus = "open" | "resolved" | "ignored";

export interface DqRule {
  key: string;
  label: string;
  severity: Severity;
  why: string;
  open: number;
  resolved: number;
  ignored: number;
}

export interface DqSummary {
  rules: DqRule[];
  open_total: number;
  resolved_total: number;
  last_scan_at: string | null;
}

export interface DqIssue {
  id: string;
  rule_key: string;
  severity: Severity;
  entity_type: "account" | "contact" | string;
  entity_id: string;
  related_ids: string[];
  title: string;
  details: Record<string, unknown> | null;
  suggested_fix: { action: string; params?: Record<string, unknown>; description: string } | null;
  status: IssueStatus;
  detected_at: string;
  last_seen_at: string;
  resolved_at: string | null;
  resolved_by: string | null;
}
