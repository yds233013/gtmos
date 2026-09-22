import type { Paged, Signal } from "@/lib/types";

export interface SignalType {
  key: string;
  name: string;
  category: string;
  default_strength: number;
  half_life_days: number;
  description: string;
}

export interface SignalFeed extends Paged<Signal> {
  by_type: Record<string, number>;
}
