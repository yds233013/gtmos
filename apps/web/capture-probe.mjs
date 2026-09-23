import { chromium } from "playwright";
const b = await chromium.launch({ channel: "chrome" });
const c = await b.newContext({ viewport: { width: 1440, height: 900 }, colorScheme: "light", baseURL: "http://127.0.0.1:3010" });
const p = await c.newPage();
for (const u of ["/pipeline","/routing","/workflows","/stack-inspector","/data-quality","/scoring","/settings?tab=controls","/accounts","/signals","/operations"]) {
  await p.goto(u, { waitUntil: "networkidle" });
  const hs = await p.evaluate(() => [...document.querySelectorAll("h1,h2,h3")].map(h => `${h.tagName} @${Math.round(h.getBoundingClientRect().top + window.scrollY)} ${h.innerText.trim().slice(0,60)}`));
  console.log("=== " + u + "\n" + hs.join("\n"));
}
await b.close();
