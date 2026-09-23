import type { Comparison, ExperimentDetail, ExperimentRow, MetricResult, Variant } from "@/components/insights/types";

/**
 * Guardrails and practical-significance fields the API adds on top of the shared experiment shapes.
 * They live here rather than in the shared types because only the experiments pages read them.
 */

export type GuardrailStatus = "ok" | "watch" | "breach" | "no_data";

export interface GuardrailCheck {
  metric: string;
  label: string;
  control: MetricResult;
  treatment: MetricResult;
  ceiling: number;
  max_regression: number;
  absolute_lift: number;
  diff_ci_low: number;
  diff_ci_high: number;
  status: GuardrailStatus;
  conclusive: boolean;
  reason: string;
  rationale: string;
}

export type RecommendationAction = "ship" | "do_not_ship" | "keep_running" | "no_change";

export interface Recommendation {
  action: RecommendationAction;
  headline: string;
  reasoning: string;
  blocking_guardrails: string[];
  watch_guardrails: string[];
}

export interface GuardedComparison extends Comparison {
  mde_abs: number | null;
  mde_relative: number | null;
  practical_threshold: number;
  practically_significant: boolean;
  practical_interval_clears: boolean;
  practical_note: string;
}

export interface GuardedVariant extends Variant {
  guardrails: Record<string, MetricResult>;
}

export interface GuardedExperiment extends Omit<ExperimentDetail, "comparisons" | "variants"> {
  variants: GuardedVariant[];
  comparisons: Record<string, Record<string, GuardedComparison>>;
  guardrails: Record<string, Record<string, GuardrailCheck>>;
  guardrail_policy: Record<string, { ceiling: number; max_regression: number }>;
  recommendation: Recommendation | null;
}

export interface GuardedExperimentRow extends ExperimentRow {
  action: RecommendationAction | null;
  guardrail_breaches: string[];
}
