export interface ScoringBucket {
  label: string;
  n: number;
  positives: number;
  rate: number;
  ci_low: number;
  ci_high: number;
  lift: number;
  small_sample: boolean;
  score_min: number | null;
  score_max: number | null;
}

export interface ScoringVariant {
  label: string;
  leakage: string;
  n: number;
  positives: number;
  base_rate: number;
  auc: number | null;
  auc_ci: [number, number] | null;
  buckets: ScoringBucket[];
  precision_at_k: { k: number; hits: number; precision: number; random_expected: number; lift: number; recall: number }[];
  monotonic: boolean;
  warnings: string[];
}

export interface ScoringOutcome {
  label: string;
  definition: string;
  by_grade: ScoringBucket[];
  variants: { structural: ScoringVariant; pre_engagement: ScoringVariant; total: ScoringVariant };
  leakage_delta:
    | { available: false }
    | { available: true; structural_auc: number; total_auc: number; delta: number; interpretation: string };
  selection_effect:
    | { available: false }
    | {
        available: true;
        contacted_only_auc: number;
        contacted_only_n: number;
        all_accounts_auc: number;
        all_accounts_n: number;
        note: string;
      };
}

export interface ScoringEvaluation {
  population: { scored_accounts: number; contacted: number; evaluated: number; excluded_from_ranking: number; note: string };
  grade_distribution: { grade: string; accounts: number; share: number }[];
  outcomes: Record<string, ScoringOutcome>;
  caveats: string[];
}
