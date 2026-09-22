import type { Paged, Signal } from "@/lib/types";

export interface SignalType {
  key: string;
  name: string;
  category: string;
  default_strength: number;
  half_life_days: number;
  description: string;
  /** A disqualifying signal: it subtracts points instead of adding them. */
  is_negative: boolean;
  /** What a rep should do about it. A negative signal is an instruction, not a data point. */
  action: string;
}

export interface SignalFeed extends Paged<Signal> {
  by_type: Record<string, number>;
}
