// TEMPORARY capture helper — delete after use.
import { chromium, devices } from "playwright";
import fs from "node:fs";
import path from "node:path";

const BASE = "http://127.0.0.1:3010";
const OUT = path.resolve("../../docs/screenshots");
const PROBE = process.argv.includes("--probe");
const ONLY = (process.argv.find((a) => a.startsWith("--only=")) || "").split("=")[1];

const KESTREL = "c5c23567-74a1-5483-bc14-224b4eb057e6";

/** full: true => fullPage, false => viewport only */
const PAGES = [
  { file: "01-overview", url: "/", heading: "Command center", full: true },
  { file: "02-accounts", url: "/accounts", heading: "Accounts", full: true },
  { file: "03-account-kestrel", url: `/accounts/${KESTREL}`, heading: "Kestrel Analytics", full: true },
  { file: "04-scoring", url: "/scoring", heading: null, full: true },
  { file: "05-signals", url: "/signals", heading: null, full: true },
  { file: "06-pipeline", url: "/pipeline", heading: null, full: true },
  { file: "07-experiments", url: "/experiments", heading: null, full: true },
  { file: "08-experiment-provocative-subject", url: "/experiments/provocative-subject", heading: null, full: true },
  { file: "09-routing", url: "/routing", heading: null, full: true },
  { file: "10-workflows", url: "/workflows", heading: null, full: true },
  { file: "11-data-quality", url: "/data-quality", heading: null, full: true },
  { file: "12-stack-inspector", url: "/stack-inspector", heading: null, full: true },
  { file: "13-approvals", url: "/approvals", heading: null, full: true },
  { file: "14-copilot", url: "/copilot", heading: null, full: true },
  { file: "15-settings-controls", url: "/settings?tab=controls", heading: null, full: true },
  { file: "16-operations", url: "/operations", heading: null, full: true },
];

const VIEWPORT_ONLY = new Set((process.env.VIEWPORT_ONLY || "").split(",").filter(Boolean));

const STYLE = `
  *, *::before, *::after {
    caret-color: transparent !important;
    animation-duration: 0s !important;
    animation-delay: 0s !important;
    transition-duration: 0s !important;
    transition-delay: 0s !important;
  }
  aside.sticky { position: static !important; height: auto !important; }
`;

async function settle(page, { chart = true } = {}) {
  await page.waitForLoadState("networkidle").catch(() => {});
  await page.waitForFunction(() => document.querySelectorAll("[data-loading], .animate-pulse").length === 0, null, { timeout: 15000 }).catch(() => {});
  if (chart) {
    await page.waitForFunction(() => {
      const svgs = [...document.querySelectorAll("svg.recharts-surface, .recharts-wrapper svg")];
      return svgs.length === 0 || svgs.every((s) => s.getBoundingClientRect().height > 0 && s.querySelector("path, rect, line, circle, text"));
    }, null, { timeout: 15000 }).catch(() => {});
  }
  await page.addStyleTag({ content: STYLE });
  await page.mouse.move(2000, 2000);
  await page.evaluate(() => { if (document.activeElement instanceof HTMLElement) document.activeElement.blur(); });
  await page.waitForTimeout(700);
}

async function inspect(page) {
  return page.evaluate(() => {
    const txt = document.body.innerText;
    return {
      h1: document.querySelector("h1")?.innerText?.trim() ?? null,
      height: document.documentElement.scrollHeight,
      chars: txt.length,
      svgs: document.querySelectorAll("svg").length,
      tables: document.querySelectorAll("table").length,
      skeletons: document.querySelectorAll(".animate-pulse").length,
      bad: /application error|something went wrong|failed to (load|fetch)|unhandled runtime error|500 internal|this page could not be found/i.test(txt),
      head: txt.slice(0, 300).replace(/\s+/g, " "),
    };
  });
}

fs.mkdirSync(OUT, { recursive: true });

const browser = await chromium.launch({ channel: "chrome" });
const ctx = await browser.newContext({
  viewport: { width: 1440, height: 900 },
  deviceScaleFactor: 2,
  colorScheme: "light",
  reducedMotion: "reduce",
  baseURL: BASE,
});
const page = await ctx.newPage();

const report = [];
for (const p of PAGES) {
  if (ONLY && !p.file.includes(ONLY)) continue;
  await page.goto(p.url, { waitUntil: "domcontentloaded" });
  await settle(page);
  const info = await inspect(page);
  const full = p.full && !VIEWPORT_ONLY.has(p.file);
  if (!PROBE) {
    if (info.bad) {
      report.push({ ...p, ...info, status: "SKIPPED-ERROR" });
      console.log(`!! ${p.file} ${p.url} -> ERROR PAGE: ${info.head}`);
      continue;
    }
    const out = path.join(OUT, `${p.file}.png`);
    await page.screenshot({ path: out, fullPage: full, animations: "disabled", caret: "hide", scale: "device" });
    const size = fs.statSync(out).size;
    report.push({ ...p, ...info, mode: full ? "full" : "viewport", kb: Math.round(size / 1024), status: "ok" });
    console.log(`${p.file}\t${full ? "full" : "view"}\th=${info.height}\t${Math.round(size / 1024)}KB\th1=${info.h1}`);
  } else {
    report.push({ ...p, ...info });
    console.log(`${p.file}\th=${info.height}\tsvg=${info.svgs}\ttbl=${info.tables}\tskel=${info.skeletons}\tbad=${info.bad}\th1=${info.h1}\t| ${info.head.slice(0, 120)}`);
  }
}

// Mobile
if (!ONLY || ONLY === "mobile") {
  const mctx = await browser.newContext({
    ...devices["Pixel 7"],
    colorScheme: "light",
    reducedMotion: "reduce",
    baseURL: BASE,
  });
  const mp = await mctx.newPage();
  await mp.goto("/", { waitUntil: "domcontentloaded" });
  await settle(mp);
  const minfo = await inspect(mp);
  if (!PROBE) {
    const out = path.join(OUT, "17-mobile-overview.png");
    await mp.screenshot({ path: out, fullPage: false, animations: "disabled", caret: "hide", scale: "device" });
    console.log(`17-mobile-overview\tview\th=${minfo.height}\t${Math.round(fs.statSync(out).size / 1024)}KB\tbad=${minfo.bad}`);
  } else {
    console.log(`mobile\th=${minfo.height}\tbad=${minfo.bad}\t| ${minfo.head.slice(0, 120)}`);
  }
  await mctx.close();
}

await browser.close();
fs.writeFileSync("/private/tmp/claude-501/-Users-yashshah2311/1055b710-4dee-4b4f-80d3-eef80ceb5716/scratchpad/shots-report.json", JSON.stringify(report, null, 2));
