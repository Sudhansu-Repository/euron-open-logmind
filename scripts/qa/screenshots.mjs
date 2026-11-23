/**
 * Curated README screenshots and tour frames from the seeded stack (real data only).
 *
 *   make up && make demo
 *   make screenshots                 (or: cd scripts/qa && node screenshots.mjs)
 *   scripts/qa/make-tour.sh          (stitches the frames into docs/assets/tour.gif)
 *
 * Every capture is the real dashboard on the demo organization, Lumen Retail, project
 * "Storefront": the logs were ingested through the API, the error groups were built by
 * ingestion, the investigation was run by the worker against the mock AI service and its
 * citations are verified live against ClickHouse in the capture. Nothing is edited.
 *
 * Writes docs/assets/screenshots/NN-name.png and scripts/qa/output/tour/NN.png.
 */
import { copyFile, mkdir, rm } from "node:fs/promises";
import { existsSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import puppeteer from "puppeteer";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const BASE = process.env.QA_BASE ?? "http://localhost:6010";
const PASSWORD = process.env.LM_DEMO_PASSWORD ?? process.env.QA_PASSWORD ?? "Demo-Owner-Pass-1";
const EMAIL = "owner@lumen.example";
const SHOTS = path.resolve(HERE, "../../docs/assets/screenshots");
const TOUR = path.resolve(HERE, "output/tour");
const CHROME = process.env.CHROME_PATH && existsSync(process.env.CHROME_PATH) ? process.env.CHROME_PATH : undefined;
const DESKTOP = { width: 1440, height: 900, deviceScaleFactor: 1 };
const PHONE = { width: 390, height: 844, isMobile: true, hasTouch: true, deviceScaleFactor: 2 };
const COOKIE = "lm_session";

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function signIn(email, password) {
  const resp = await fetch(`${BASE}/api/session`, {
    method: "POST",
    headers: { "content-type": "application/json", origin: BASE },
    body: JSON.stringify({ action: "login", email, password }),
  });
  if (!resp.ok) throw new Error(`sign-in failed (${resp.status}): ${await resp.text()}. Run make demo first.`);
  const setCookie = resp.headers.get("set-cookie");
  const match = setCookie && /lm_session=([^;]+)/.exec(setCookie);
  if (!match) throw new Error("sign-in succeeded but set no lm_session cookie");
  return match[1];
}

async function api(token, url) {
  const resp = await fetch(`${BASE}${url}`, { headers: { cookie: `${COOKIE}=${token}` } });
  if (!resp.ok) throw new Error(`GET ${url}: ${resp.status}`);
  return resp.json();
}

let PROJECT = "";

async function newPage(browser, token, viewport, theme = "light") {
  const ctx = await browser.createBrowserContext();
  if (token) await ctx.setCookie({ name: COOKIE, value: token, url: BASE, httpOnly: true, sameSite: "Lax" });
  const page = await ctx.newPage();
  await page.setViewport(viewport);
  // Reports quote times in UTC; showing the dashboard in UTC too keeps the captures consistent.
  await page.emulateTimezone("UTC");
  await page.evaluateOnNewDocument(
    (t, projectId) => {
      try {
        localStorage.setItem("theme", t);
        if (projectId) localStorage.setItem("logmind.ui", JSON.stringify({ state: { sidebarCollapsed: false, projectId }, version: 1 }));
      } catch {
        // The page then follows the system theme.
      }
    },
    theme,
    PROJECT
  );
  page.on("pageerror", (e) => console.warn(`page error on ${page.url()}: ${e}`));
  return page;
}

/** Wait until the page has data: no loading placeholders, the network quiet. */
async function settle(page) {
  await page.waitForFunction(() => !document.querySelector("[aria-busy=true],[aria-busy='']"), { timeout: 30_000 }).catch(() => {});
  await sleep(900);
}

async function open(page, url) {
  await page.goto(`${BASE}${url}`, { waitUntil: "networkidle2", timeout: 60_000 });
  await settle(page);
}

/** Click the first enabled button whose text is (or starts with) the given text. Scoped to
 * buttons only, never the sidebar nav's links. */
async function click(page, text) {
  await page.waitForFunction(
    (t) => [...document.querySelectorAll("button")].some((b) => !b.disabled && b.textContent.trim().startsWith(t)),
    { timeout: 20_000 },
    text,
  );
  await page.evaluate((t) => {
    const all = [...document.querySelectorAll("button")].filter((b) => !b.disabled);
    (all.find((b) => b.textContent.trim() === t) ?? all.find((b) => b.textContent.trim().startsWith(t))).click();
  }, text);
}

async function waitText(page, re, timeout = 30_000) {
  await page.waitForFunction((src) => new RegExp(src).test(document.body.innerText), { timeout }, re.source);
}

const written = [];
async function shot(page, name, { full = false } = {}) {
  const file = path.join(SHOTS, `${name}.png`);
  await page.evaluate(() => window.scrollTo(0, 0));
  await sleep(200);
  await page.screenshot({ path: file, fullPage: full });
  written.push(file);
  console.log(`wrote ${path.relative(path.resolve(HERE, "../.."), file)}`);
  return file;
}

async function main() {
  await rm(SHOTS, { recursive: true, force: true });
  await rm(TOUR, { recursive: true, force: true });
  await mkdir(SHOTS, { recursive: true });
  await mkdir(TOUR, { recursive: true });
  const token = await signIn(EMAIL, PASSWORD);

  const projects = await api(token, "/api/proxy/api/v1/projects");
  const store = projects.find((p) => p.name === "Storefront") ?? projects[0];
  if (!store) throw new Error("the demo has no project: run make demo");
  PROJECT = store.id;
  const q = `project_id=${store.id}`;
  const groups = await api(token, `/api/proxy/api/v1/errors?${q}&sort=occurrences`);
  const timeout = groups.items.find((g) => g.exception_type === "PaymentGatewayTimeout") ?? groups.items[0];
  const investigations = await api(token, `/api/proxy/api/v1/ai/investigations?${q}`);
  const inv = investigations.find((i) => i.status === "completed");
  const alerts = await api(token, `/api/proxy/api/v1/alerts?${q}`);
  const firing = alerts.find((a) => a.state === "firing") ?? alerts[0];
  if (!timeout || !inv || !firing) throw new Error("the demo data is incomplete: run make demo");

  const browser = await puppeteer.launch({ headless: true, executablePath: CHROME, args: ["--no-sandbox"] });
  const tour = [];
  try {
    let page = await newPage(browser, null, DESKTOP);
    await open(page, "/login");
    tour.push(await shot(page, "00-sign-in"));
    await page.browserContext().close();

    page = await newPage(browser, token, DESKTOP);
    await open(page, "/overview");
    tour.push(await shot(page, "01-overview"));

    await open(page, "/logs?range=1h");
    tour.push(await shot(page, "02-log-explorer"));

    await open(page, "/logs?range=6h&q=timeout");
    await page.evaluate(() => document.querySelector("[data-qa=log-row]")?.click());
    await waitText(page, /Stack trace/, 20_000).catch(() => {});
    await sleep(600);
    tour.push(await shot(page, "03-log-detail"));

    await open(page, "/live");
    await sleep(1500);
    await shot(page, "04-live-logs");

    await open(page, "/errors");
    tour.push(await shot(page, "05-errors"));

    await open(page, `/errors/${timeout.id}`);
    tour.push(await shot(page, "06-error-detail"));

    await open(page, `/investigations/${inv.id}`);
    await click(page, "Verify citations");
    await waitText(page, /cited lines were re-read/, 30_000);
    await sleep(500);
    tour.push(await shot(page, "07-investigation", { full: true }));

    await open(page, "/investigations");
    await shot(page, "08-investigations");

    await open(page, "/services");
    tour.push(await shot(page, "09-services"));

    await open(page, "/alerts");
    tour.push(await shot(page, "10-alerts"));

    await open(page, `/alerts/${firing.id}`);
    await shot(page, "11-alert-detail");

    await open(page, "/settings?tab=projects");
    await click(page, "Preview redaction");
    await waitText(page, /REDACTED/, 20_000);
    tour.push(await shot(page, "12-redaction"));

    await open(page, "/settings?tab=ai");
    await shot(page, "13-ai-providers");
    await page.browserContext().close();

    page = await newPage(browser, token, DESKTOP, "dark");
    await open(page, "/overview");
    tour.push(await shot(page, "14-overview-dark"));
    await open(page, `/investigations/${inv.id}`);
    await shot(page, "15-investigation-dark");
    await page.browserContext().close();

    page = await newPage(browser, token, PHONE);
    await open(page, "/errors");
    await shot(page, "16-errors-phone");
    await open(page, `/investigations/${inv.id}`);
    tour.push(await shot(page, "17-investigation-phone"));
    await page.browserContext().close();
  } finally {
    await browser.close();
  }
  for (const [i, file] of tour.entries()) await copyFile(file, path.join(TOUR, `${String(i).padStart(2, "0")}.png`));
  console.log(`\n${written.length} screenshots in docs/assets/screenshots, ${tour.length} tour frames in scripts/qa/output/tour`);
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
