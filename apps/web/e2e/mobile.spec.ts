import { expect, test } from "@playwright/test";

for (const path of ["/", "/accounts", "/approvals", "/stack-inspector", "/pipeline"]) {
  test(`no horizontal page scroll on mobile: ${path}`, async ({ page }) => {
    await page.goto(path);
    await expect(page.locator("h1").first()).toBeVisible();
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
    expect(overflow).toBeLessThanOrEqual(1);
  });
}

test("mobile navigation opens and navigates", async ({ page }) => {
  await page.goto("/");
  await page.waitForLoadState("networkidle");
  await page.getByRole("button", { name: "Open navigation" }).click();
  await page.getByRole("link", { name: "Signals" }).click();
  await expect(page).toHaveURL(/\/signals/);
});
