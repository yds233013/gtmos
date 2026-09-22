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

  for (const path of ["/signals", "/contacts", "/pipeline", "/campaigns", "/experiments", "/workflows",
    "/data-quality", "/operations", "/scoring", "/settings"]) {
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
