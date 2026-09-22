import { describe, expect, it } from "vitest";

import { hrefWith, apiQuery, intParam, oneOf } from "@/components/revenue/query";
import { describeCondition } from "@/components/systems/conditions";

describe("query helpers", () => {
  it("drops empty values and resets page when filters change", () => {
    expect(hrefWith("/signals", { days: "30", page: "3" }, { type: "funding_round" })).toBe(
      "/signals?days=30&type=funding_round",
    );
    expect(hrefWith("/signals", { days: "30" }, { page: 2 })).toBe("/signals?days=30&page=2");
    expect(apiQuery({ a: 1, b: "", c: null, d: "x" })).toBe("a=1&d=x");
  });
  it("clamps and validates params", () => {
    expect(intParam("abc", 1)).toBe(1);
    expect(intParam("999999", 1)).toBe(10000);
    expect(oneOf("30", ["7", "30"] as const)).toBe("30");
    expect(oneOf("5", ["7", "30"] as const)).toBeUndefined();
  });
});

describe("condition descriptions", () => {
  it("renders rule conditions as readable text", () => {
    expect(describeCondition({ field: "account.icp_score", op: "gte", value: 75 })).toContain("≥ 75");
    expect(describeCondition({ field: "account.segment", op: "in", value: ["strategic", "enterprise"] })).toContain(
      "Strategic, Enterprise",
    );
  });
});
