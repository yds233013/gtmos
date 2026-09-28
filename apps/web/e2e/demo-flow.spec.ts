import { expect, type Page, test } from "@playwright/test";

/** Navigate and wait until client components are hydrated (dev servers compile on demand). */
async function open(page: Page, path: string) {
  await page.goto(path);
  await page.waitForLoadState("networkidle");
}

test.describe("GTMOS demo flow", () => {
  test.skip(({ isMobile }) => !!isMobile, "desktop flow");

  test("command center explains itself and labels demo data", async ({ page }) => {
    await page.goto("/");
    await expect(page.getByRole("heading", { name: "Command center" })).toBeVisible();
    await expect(page.getByText("Synthetic demo data")).toBeVisible();
    await expect(page.getByText("No external messages are ever sent")).toBeVisible();
    await expect(page.getByText("Pipeline created by week")).toBeVisible();
  });

  test("flagship account: explainable score, committee and cited research", async ({ page }) => {
    await open(page, "/accounts?q=kestrel");
    await page.getByRole("link", { name: "Kestrel Analytics" }).first().click();
    await expect(page.getByRole("heading", { name: "Kestrel Analytics" })).toBeVisible();
    await page.waitForLoadState("networkidle");
    await expect(page.getByText("Why this score")).toBeVisible();
    await expect(page.getByText("AI/ML hiring surge").first()).toBeVisible();
    await page.getByRole("tab", { name: "Buying committee" }).click();
    await expect(page.getByText("Priya Raman").first()).toBeVisible();
    await page.getByRole("tab", { name: "Research" }).click();
    await expect(page.getByText("Account research")).toBeVisible();
    await expect(page.getByRole("link", { name: /Evidence E\d+/ }).first()).toBeVisible();
  });

  test("approval queue shows guardrails and never offers a send button", async ({ page }) => {
    await page.goto("/approvals");
    await expect(page.getByText("GTMOS never sends messages", { exact: false }).first()).toBeVisible();
    await expect(page.getByText(/guardrail/i).first()).toBeVisible();
    await expect(page.getByRole("button", { name: /^send$/i })).toHaveCount(0);
  });

  test("routing simulator explains the decision", async ({ page }) => {
    await open(page, "/routing");
    await page.getByRole("button", { name: /simulate routing/i }).click();
    await expect(page.getByText(/Matched rule|No routing rule matched/).first()).toBeVisible();
  });

  test("copilot answers from approved metrics", async ({ page }) => {
    await open(page, "/copilot");
    await expect(page.getByText("The Copilot never writes SQL")).toBeVisible();
    const input = page.getByRole("textbox").first();
    await input.fill("Which segment has the highest meeting conversion?");
    await page.getByRole("button", { name: /^ask$/i }).click();
    await expect(page.getByText(/highest meeting rate/i)).toBeVisible();
  });

  test("stack inspector ranks automation opportunities with evidence", async ({ page }) => {
    await page.goto("/stack-inspector");
    await expect(page.getByRole("heading", { name: "GTM Stack Inspector" })).toBeVisible();
    await expect(page.getByText("Automation opportunities").first()).toBeVisible();
  });

  test("integrations page states how far each boundary has actually been verified", async ({ page }) => {
    // The expectation is derived from the API rather than hardcoded, because the honest answer is a
    // property of the *instance*, not of the codebase. A developer laptop that has run the n8n
    // container reports one boundary reached; a freshly seeded public deployment has reached none and
    // says "0 of 4". Both are correct, and an assertion pinned to either number fails on the other —
    // this test asserted 3 and broke the first time it ran against production.
    const status = await page.request.get("/api/v1/integrations/status?days=7");
    expect(status.ok()).toBeTruthy();
    const body = await status.json();
    const unreached = body.integrations.filter((i: { reached_real_service: boolean }) => !i.reached_real_service);

    await page.goto("/integrations");
    await expect(page.getByRole("heading", { name: "Integrations", level: 1 })).toBeVisible();
    await expect(page.getByText("Real service never reached")).toHaveCount(unreached.length);
    await expect(page.getByText(`${body.integrations.length - unreached.length} of ${body.integrations.length}`)).toBeVisible();
    // Whatever the counts, no boundary may ever be badged as connected.
    await expect(page.getByText("Connected", { exact: true })).toHaveCount(0);
  });

  for (const path of ["/signals", "/contacts", "/pipeline", "/campaigns", "/experiments", "/workflows",
    "/data-quality", "/operations", "/scoring", "/settings", "/integrations", "/integrations/n8n"]) {
    test(`page ${path} renders without an error boundary`, async ({ page }) => {
      const errors: string[] = [];
      page.on("pageerror", (e) => errors.push(e.message));
      await page.goto(path);
      await expect(page.locator("h1").first()).toBeVisible();
      await expect(page.getByText("This page failed to load")).toHaveCount(0);
      expect(errors).toEqual([]);
    });
  }
});
