import { describe, expect, it } from "vitest";

import { money, num, pct, relTime, segment, titleCase } from "@/lib/format";

describe("format", () => {
  it("formats money compactly above 100k", () => {
    expect(money(180000)).toBe("$180K");
    expect(money(4_990_000)).toBe("$5M");
    expect(money(59350)).toBe("$59,350");
    expect(money(null)).toBe("—");
  });
  it("formats numbers and percents", () => {
    expect(num(11819)).toBe("11,819");
    expect(pct(0.0571)).toBe("5.7%");
    expect(pct(undefined)).toBe("—");
  });
  it("renders relative time deterministically", () => {
    const now = new Date("2026-09-22T12:00:00Z");
    expect(relTime("2026-09-22T11:59:30Z", now)).toBe("just now");
    expect(relTime("2026-09-22T09:00:00Z", now)).toBe("3h ago");
    expect(relTime("2026-09-10T12:00:00Z", now)).toBe("12d ago");
    expect(relTime(null, now)).toBe("—");
  });
  it("title-cases GTM vocabulary", () => {
    expect(titleCase("ai_hiring_surge")).toBe("AI Hiring Surge");
    expect(titleCase("sync_crm")).toBe("Sync CRM");
    expect(segment("mid_market")).toBe("Mid-Market");
  });
});
