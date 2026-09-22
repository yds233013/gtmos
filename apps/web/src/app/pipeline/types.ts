import type { Opportunity } from "@/lib/types";

export type DealStage = "discovery" | "evaluation" | "proposal" | "negotiation" | "closed_won" | "closed_lost";

export interface OpportunityList {
  items: (Opportunity & { owner_id?: string | null; stage: DealStage | string })[];
}

export interface Velocity {
  window_days: number;
  closed_deals: number;
  win_rate: number;
  avg_won_deal: number;
  median_cycle_days: number | null;
  open_opportunities: number;
  pipeline_velocity_per_day: number;
  formula: string;
  stage_durations: { from: string; to: string; accounts: number; median_days: number | null }[];
  low_sample: boolean;
}

export type AttributionModel = "first_touch" | "last_touch" | "linear" | "u_shaped";

export interface AttributionRow {
  key: string;
  first_touch: number;
  last_touch: number;
  linear: number;
  u_shaped: number;
  first_touch_won?: number;
  last_touch_won?: number;
  linear_won?: number;
  u_shaped_won?: number;
}

export interface AttributionCredit {
  source: string;
  share: number;
  amount: number;
}

/** One opportunity where the four models credit different campaigns — the teaching example. */
export interface AttributionSpotlight {
  opportunity_id: string;
  opportunity: string;
  account_id: string;
  account: string | null;
  amount: number;
  opened_at: string;
  won: boolean;
  touches: { source: string; occurred_at: string; days_before_open: number }[];
  credit: Record<AttributionModel, AttributionCredit[]>;
  disagreement: string;
}

export interface Attribution {
  window_days: number;
  models: AttributionModel[];
  rows: AttributionRow[];
  opportunities: number;
  total_pipeline: number;
  unattributed_opportunities: number;
  unattributed_pipeline: number;
  attributed_share?: number;
  spotlight: AttributionSpotlight | null;
  limitations: string[];
}

export interface StuckAccount {
  account_id: string;
  name: string;
  stage: string;
  days_in_stage: number;
  rule: string;
  owner_id: string | null;
  region: string | null;
  icp_score: number | null;
}

export interface Stuck {
  by_stage: Record<string, number>;
  unowned_by_stage: Record<string, number>;
  accounts: StuckAccount[];
  total: number;
}

export interface OwnerLoad {
  user_id: string;
  name: string;
  team: string | null;
  is_active: boolean;
}
