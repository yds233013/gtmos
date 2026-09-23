import { chromium } from '@playwright/test';

const BASE = 'http://localhost:3010';
const OUT = '../../docs/screenshots';

const shots = [
  {
    file: '01-overview.png',
    path: '/',
    ready: async (page) => {
      await page.getByText('Command center', { exact: false }).first().waitFor({ state: 'visible', timeout: 60000 });
      // a real numeric stat must be rendered (not a skeleton)
      await page.waitForFunction(() => {
        const t = document.body.innerText;
        return /\d{1,3}(,\d{3})+/.test(t) || /\$\d/.test(t);
      }, null, { timeout: 60000 });
    },
  },
  {
    file: '03-account-kestrel.png',
    path: '/accounts/c5c23567-74a1-5483-bc14-224b4eb057e6',
    ready: async (page) => {
      await page.getByText('Kestrel Analytics', { exact: false }).first().waitFor({ state: 'visible', timeout: 60000 });
      await page.waitForFunction(() => {
        const t = document.body.innerText;
        return t.includes('Raised $120M Series C') || t.includes('Crossed the free-tier trace volume threshold');
      }, null, { timeout: 60000 });
    },
  },
];

const browser = await chromium.launch();
const context = await browser.newContext({
  viewport: { width: 1440, height: 900 },
  deviceScaleFactor: 2,
  colorScheme: 'light',
});
// make sure nothing is served from a stale cache
await context.route('**/*', (route) => {
  const headers = { ...route.request().headers(), 'cache-control': 'no-cache', pragma: 'no-cache' };
  route.continue({ headers });
});

for (const shot of shots) {
  const page = await context.newPage();
  await page.goto(BASE + shot.path, { waitUntil: 'domcontentloaded' });
  await page.waitForLoadState('networkidle');
  await shot.ready(page);
  await page.waitForLoadState('networkidle');
  // let any chart/animation settle
  await page.waitForTimeout(2500);
  // ensure lazy content below the fold has mounted, then return to top
  await page.evaluate(async () => {
    const step = window.innerHeight;
    for (let y = 0; y < document.body.scrollHeight; y += step) {
      window.scrollTo(0, y);
      await new Promise((r) => setTimeout(r, 180));
    }
    window.scrollTo(0, 0);
    await new Promise((r) => setTimeout(r, 400));
  });
  await page.waitForLoadState('networkidle');
  await page.waitForTimeout(1200);

  const text = await page.evaluate(() => document.body.innerText);
  const hasSeriesD = /Series\s+D/i.test(text);
  const hasSkeleton = (await page.locator('[class*="animate-pulse"]').count()) > 0;
  console.log(`${shot.file}: seriesD=${hasSeriesD} skeletons=${hasSkeleton} chars=${text.length}`);

  await page.screenshot({ path: `${OUT}/${shot.file}`, fullPage: true });
  await page.close();
}

await browser.close();
console.log('done');
