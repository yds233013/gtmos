import type { Draft } from "@/lib/types";

export type DraftStatus = Draft["status"];

/** Row shape returned by GET /drafts (adds fields the shared Draft type does not declare). */
export interface DraftRow extends Draft {
  reviewed_by?: string | null;
  rejection_reason?: string | null;
  research_report_id?: string | null;
  campaign_id?: string | null;
  updated_at?: string;
}

export interface DraftList {
  items: DraftRow[];
  counts: Partial<Record<DraftStatus, number>>;
}
