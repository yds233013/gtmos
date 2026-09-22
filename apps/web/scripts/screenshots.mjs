// Captures README screenshots from a running GTMOS (default: production build on :3011).
// Usage: node scripts/screenshots.mjs [baseUrl]
import { chromium } from "@playwright/test";

const base = process.argv[2] ?? "http://127.0.0.1:3011";
const out = new URL("../../../docs/screenshots/", import.meta.url).pathname;
const api = process.env.API_URL ?? "http://127.0.0.1:8010";

const ws = await (await fetch(`${api}/api/v1/workspace`)).json();
const pages = [
  ["01-overview", "/"],
  ["02-accounts", "/accounts?grade=A&grade=B"],
  ["03-account-score", `/accounts/${ws.flagship_account_id}`],
  ["04-approvals", "/approvals"],
  ["05-workflows", "/workflows"],
  ["06-routing", "/routing"],
  ["07-experiment", "/experiments/funding-vs-generic"],
  ["08-stack-inspector", "/stack-inspector"],
  ["09-data-quality", "/data-quality"],
  ["10-operations", "/operations"],
  ["11-pipeline", "/pipeline"],
  ["12-copilot", "/copilot"],
];

const browser = await chromium.launch({ channel: "chrome" });
const context = await browser.newContext({ viewport: { width: 1440, height: 900 }, colorScheme: "light", deviceScaleFactor: 1 });
const page = await context.newPage();
for (const [name, path] of pages) {
  await page.goto(base + path, { waitUntil: "networkidle" });
  if (name === "12-copilot") {
    await page.getByRole("textbox").first().fill("Why did pipeline fall?");
    await page.getByRole("button", { name: /^ask$/i }).click();
    await page.getByText("Pipeline created").first().waitFor();
  }
  await page.screenshot({ path: `${out}${name}.png`, fullPage: false });
  console.log("saved", name);
}
// Research tab of the flagship account
await page.goto(`${base}/accounts/${ws.flagship_account_id}`, { waitUntil: "networkidle" });
await page.getByRole("tab", { name: "Research" }).click();
await page.getByText("Account research").waitFor();
await page.screenshot({ path: `${out}03b-account-research.png` });
console.log("saved 03b-account-research");
await browser.close();
