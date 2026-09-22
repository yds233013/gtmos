import { segment, titleCase } from "@/lib/format";

/** The condition language shared by workflow triggers/conditions and routing rules: data, never code. */
export interface Condition {
  field: string;
  op: string;
  value?: unknown;
}

export const OP_LABEL: Record<string, string> = {
  eq: "is",
  neq: "is not",
  in: "is one of",
  not_in: "is not one of",
  gte: "≥",
  lte: "≤",
  gt: ">",
  lt: "<",
  exists: "is set",
  not_exists: "is not set",
  contains: "contains",
};

const FIELD_LABEL: Record<string, string> = {
  "account.icp_score": "ICP score",
  "account.intent_score": "Intent score",
  "account.is_customer": "Is customer",
  "account.region": "Region",
  "account.segment": "Segment",
  "account.score_grade": "Grade",
  "signal.signal_type": "Signal type",
  "event.threshold": "Usage threshold",
};

export function fieldLabel(field: string): string {
  if (FIELD_LABEL[field]) return FIELD_LABEL[field];
  const last = field.split(".").pop() ?? field;
  return titleCase(last);
}

function scalar(field: string, v: unknown): string {
  if (v === null || v === undefined) return "empty";
  if (typeof v === "boolean") return v ? "yes" : "no";
  if (typeof v === "number") return String(v);
  const s = String(v);
  if (field.endsWith(".segment")) return segment(s);
  if (field.endsWith(".region") || field.endsWith("grade")) return s;
  if (field.endsWith("_type")) return titleCase(s);
  return s;
}

export function valueLabel(field: string, value: unknown): string {
  if (Array.isArray(value)) return value.map((v) => scalar(field, v)).join(", ");
  return scalar(field, value);
}

/** "ICP score ≥ 75", "Segment is one of Strategic, Enterprise". */
export function describeCondition(c: Condition): string {
  const op = OP_LABEL[c.op] ?? c.op;
  if (c.op === "exists" || c.op === "not_exists") return `${fieldLabel(c.field)} ${op}`;
  return `${fieldLabel(c.field)} ${op} ${valueLabel(c.field, c.value)}`;
}

/** Human rendering of an arbitrary "actual" value captured at evaluation time. */
export function actualLabel(field: string | undefined, value: unknown): string {
  if (value === undefined) return "—";
  return field ? valueLabel(field, value) : Array.isArray(value) ? value.join(", ") : String(value);
}
