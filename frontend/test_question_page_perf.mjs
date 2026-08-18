// E2E regression for the 4-endpoint refactor of 项目详情页「问题提及分析」.
// Asserts: tList <= 1000ms, tDetail <= 2000ms, summaryHits <= 2,
// productHits <= 2, competitorHits == 0, statusHits == 0, oldAnalyticsHits == 0.
//
// Frontend dev server: http://localhost:5173 (vite proxies /api -> 18083).
// Backend: http://127.0.0.1:18083 (already running).
// PROJECT_ID env var overrides default "3".

import puppeteer from "/home/wangjh/projects/windx/node_modules/puppeteer-core/lib/puppeteer/puppeteer-core.js";

const projectId = process.env.PROJECT_ID ?? "3";

const LIST_BUDGET_MS = 1000;
const DETAIL_BUDGET_MS = 2000;
const SUMMARY_HIT_BUDGET = 2;
const PRODUCT_HIT_BUDGET = 2;
const NAV_TIMEOUT_MS = 30000;
const LOGIN_TIMEOUT_MS = 10000;

const browser = await puppeteer.launch({
  executablePath: "/usr/bin/google-chrome",
  headless: "new",
  args: ["--no-sandbox", "--disable-gpu", "--window-size=1440,900"],
});

try {
  const page = await browser.newPage();
  await page.setViewport({ width: 1440, height: 900 });
  // Track real uncaught exceptions separately from console.error (which
  // surfaces antd deprecation warnings unrelated to this refactor).
  const pageErrors = [];
  page.on("pageerror", (err) => pageErrors.push(err.message));
  const consoleErrors = [];
  page.on("console", (m) => { if (m.type() === "error") consoleErrors.push(m.text()); });

  // Track all /api requests so we can count per-endpoint after the SPA nav.
  const starts = new Map();
  const requests = [];
  page.on("request", (request) => {
    if (request.url().includes("/api/")) {
      starts.set(request, performance.now());
    }
  });
  page.on("response", (response) => {
    const request = response.request();
    const started = starts.get(request);
    if (started !== undefined) {
      const path = new URL(request.url()).pathname;
      requests.push({
        method: request.method(),
        path,
        status: response.status(),
        ms: Math.round(performance.now() - started),
      });
    }
  });

  // Login.
  await page.goto("http://localhost:5173/login", { waitUntil: "networkidle0", timeout: NAV_TIMEOUT_MS });
  await page.waitForSelector("input", { timeout: LOGIN_TIMEOUT_MS });
  await page.evaluate(() => {
    const setV = (el, v) => {
      const d = Object.getOwnPropertyDescriptor(Object.getPrototypeOf(el), "value");
      d.set.call(el, v);
      el.dispatchEvent(new Event("input", { bubbles: true }));
    };
    const i = document.querySelectorAll("input");
    if (i.length < 2) throw new Error("no inputs: " + i.length);
    setV(i[0], "admin");
    setV(i[1], "admin123");
  });
  await page.evaluate(() => {
    const bs = Array.from(document.querySelectorAll("button"));
    const s =
      bs.find((b) => b.textContent?.trim() === "登录") ||
      bs.find((b) => b.textContent?.trim() === "登 录") ||
      bs.find((b) => b.type === "submit");
    if (!s) throw new Error("no submit");
    s.click();
  });
  for (let i = 0; i < 50; i++) {
    const ok = await page.evaluate(() => !location.pathname.startsWith("/login"));
    if (ok) break;
    await new Promise((r) => setTimeout(r, 200));
  }
  // Wait until the post-login project page has fully rendered so /auth/me
  // has settled (RequireAuth bounces to /login while user is still null).
  await page.waitForSelector(".app-layout", { timeout: 15000 });
  await page.waitForNetworkIdle({ idleTime: 300, timeout: NAV_TIMEOUT_MS });

  // SPA-navigate to the question tab (pushState + popstate, like test_modal.mjs).
  // A full goto reload would race the new AuthProvider's /auth/me against
  // RequireAuth and bounce to /login.
  requests.length = 0;
  starts.clear();
  const t0 = performance.now();
  await page.evaluate((id) => {
    const target = `/admin/projects/${id}?tab=question`;
    history.pushState({}, "", target);
    dispatchEvent(new PopStateEvent("popstate"));
  }, projectId);

  await page.waitForSelector(".qt-list-item", { timeout: NAV_TIMEOUT_MS });
  const tList = Math.round(performance.now() - t0);
  await page.waitForSelector(".qt-detail-body", { timeout: NAV_TIMEOUT_MS });
  // Pin tDetail to the actual product-analytics response arrival — that's the
  // real "data ready" moment. Defensive waitForSelector above guards against
  // a missing selector; race guards against the request never firing.
  const productAnalyticsRegex = /\/questions\/\d+\/product-analytics$/;
  const productResponsePromise = page.waitForResponse(
    (r) => productAnalyticsRegex.test(new URL(r.url()).pathname) && r.status() === 200,
    { timeout: 30000 },
  ).then((r) => performance.now()).catch(() => null);
  const tDetailRaw = await productResponsePromise;
  const tDetail = tDetailRaw === null ? Math.round(performance.now() - t0) : Math.round(tDetailRaw - t0);

  // Count requests by endpoint.
  const summaryHits = requests.filter((r) => r.path.endsWith("/questions/summary")).length;
  const productHits = requests.filter((r) =>
    /\/questions\/\d+\/product-analytics$/.test(r.path),
  ).length;
  const competitorHits = requests.filter((r) =>
    /\/questions\/\d+\/competitor-analytics$/.test(r.path),
  ).length;
  const statusHits = requests.filter((r) => r.path.endsWith("/questions/status-changes")).length;
  const oldAnalyticsHits = requests.filter((r) => r.path.endsWith("/questions/analytics")).length;

  const result = {
    projectId,
    listMs: tList,
    detailMs: tDetail,
    summaryHits,
    productHits,
    competitorHits,
    statusHits,
    oldAnalyticsHits,
    total: requests.length,
    pageErrors: pageErrors.length,
    consoleErrors: consoleErrors.length,
  };
  console.log(JSON.stringify(result, null, 2));

  // Dump failure artifact on any assertion throw.
  const fail = async (msg) => {
    const dir = "/tmp/qdiag";
    await import("node:fs/promises").then((fs) => fs.mkdir(dir, { recursive: true }));
    const stamp = new Date().toISOString().replace(/[:.]/g, "-");
    const path = `${dir}/perf-fail-${stamp}.png`;
    try {
      await page.screenshot({ path, fullPage: true });
    } catch (e) {
      console.log("[screenshot failed]", e.message);
    }
    console.log("=== requests ===");
    console.log(JSON.stringify(requests, null, 2));
    throw new Error(msg);
  };

  try {
    if (tList > LIST_BUDGET_MS) throw new Error(`list ready >${LIST_BUDGET_MS}ms: ${tList}ms`);
    if (tDetail > DETAIL_BUDGET_MS) throw new Error(`detail ready >${DETAIL_BUDGET_MS}ms: ${tDetail}ms`);
    if (oldAnalyticsHits > 0) throw new Error(`old /questions/analytics still requested: ${oldAnalyticsHits}`);
    if (productHits > PRODUCT_HIT_BUDGET) throw new Error(`product-analytics fetched >${PRODUCT_HIT_BUDGET}x (StrictMode not deduped): ${productHits}`);
    if (summaryHits > SUMMARY_HIT_BUDGET) throw new Error(`summary fetched >${SUMMARY_HIT_BUDGET}x: ${summaryHits}`);
    if (statusHits > 0) throw new Error(`status-changes should be lazy, got ${statusHits}`);
    if (competitorHits > 0) throw new Error(`competitor should not fetch on product pane, got ${competitorHits}`);
    if (pageErrors.length > 0) throw new Error(`uncaught page errors: ${pageErrors.join(" | ")}`);
  } catch (e) {
    await fail(e.message);
  }
} finally {
  await browser.close();
}