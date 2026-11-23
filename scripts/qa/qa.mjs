/**
 * Browser QA (make qa): visits every dashboard page as the demo owner, plus the public
 * sign-in/sign-up pages, in light and dark at desktop (1440) and phone (390) width. Saves
 * a screenshot of each and fails on console errors, failed or 4xx/5xx requests, broken
 * images, error states, pages with no explanation (an empty main area), horizontal
 * overflow, or a page stuck loading after the network goes idle.
 *
 *   make qa
 *   QA_BASE=http://localhost:6010 QA_OUT=./output node qa.mjs
 *   QA_PAGES=/overview,/logs QA_THEMES=dark QA_SIZES=phone node qa.mjs
 *
 * Needs the seeded stack (make up && make demo). Signs in once through the dashboard's own
 * session bridge (POST /api/session, the same endpoint the sign-in form calls) and reuses
 * the resulting httpOnly lm_session cookie for every authenticated page. Uses Puppeteer's
 * bundled Chromium; CHROME_PATH overrides it.
 */
import { mkdir } from "node:fs/promises";
import { existsSync } from "node:fs";
import path from "node:path";
import puppeteer from "puppeteer";

const BASE = process.env.QA_BASE ?? "http://localhost:6010";
const OUT = process.env.QA_OUT ?? path.resolve("output");
const PASSWORD = process.env.LM_DEMO_PASSWORD ?? process.env.QA_PASSWORD ?? "Demo-Owner-Pass-1";
const CHROME = process.env.CHROME_PATH && existsSync(process.env.CHROME_PATH) ? process.env.CHROME_PATH : undefined;
const COOKIE = "lm_session";
const EMAIL = "owner@lumen.example";

const LIST_PAGES = [
  "/overview",
  "/live",
  "/logs",
  "/logs?range=24h&level=error",
  "/services",
  "/errors",
  "/investigations",
  "/alerts",
  "/settings",
  "/settings?tab=projects",
  "/settings?tab=keys",
  "/settings?tab=ai",
  "/settings?tab=people",
  "/settings?tab=audit",
];
const DETAIL_PAGES = ["/errors/:error", "/investigations/:investigation", "/alerts/:alert"];

const ROLE_PAGES = {
  anonymous: ["/login", "/signup"],
  owner: [...LIST_PAGES, ...DETAIL_PAGES],
};

const ONLY = process.env.QA_PAGES ? new Set(process.env.QA_PAGES.split(",")) : null;
const ROLES = (process.env.QA_ROLES ?? "anonymous,owner").split(",");
const THEMES = (process.env.QA_THEMES ?? "light,dark").split(",");
const SIZES = {
  desktop: { width: 1440, height: 900 },
  phone: { width: 390, height: 844, isMobile: true, hasTouch: true, deviceScaleFactor: 2 },
};
const SIZE_KEYS = (process.env.QA_SIZES ?? "desktop,phone").split(",");

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

function slug(p) {
  return p.replace(/^\//, "").replace(/[/:?=&]/g, "-") || "home";
}

/** Signs in through the dashboard's own session bridge (what the sign-in form calls) and
 * returns the httpOnly lm_session cookie's value from the Set-Cookie header. */
async function signIn(email, password) {
  const resp = await fetch(`${BASE}/api/session`, {
    method: "POST",
    headers: { "content-type": "application/json", origin: BASE },
    body: JSON.stringify({ action: "login", email, password }),
  });
  if (!resp.ok) throw new Error(`sign-in for ${email} failed (${resp.status}): ${await resp.text()}. Run make demo first.`);
  const setCookie = resp.headers.get("set-cookie");
  const match = setCookie && /lm_session=([^;]+)/.exec(setCookie);
  if (!match) throw new Error("sign-in succeeded but set no lm_session cookie");
  return match[1];
}

async function api(token, url) {
  const resp = await fetch(`${BASE}${url}`, { headers: { cookie: `${COOKIE}=${token}` } });
  if (!resp.ok) throw new Error(`GET ${url}: ${resp.status} ${await resp.text()}`);
  return resp.json();
}

/** Ids of seeded records for the parameterised pages (the Storefront project). */
async function resolveIds(token) {
  const projects = await api(token, "/api/proxy/api/v1/projects");
  const store = projects.find((p) => p.name === "Storefront") ?? projects[0];
  if (!store) throw new Error("the demo has no projects: run make demo");
  const q = `project_id=${store.id}`;
  const [errors, investigations, alerts] = await Promise.all([
    api(token, `/api/proxy/api/v1/errors?${q}&sort=occurrences`),
    api(token, `/api/proxy/api/v1/ai/investigations?${q}`),
    api(token, `/api/proxy/api/v1/alerts?${q}`),
  ]);
  const pick = (list, name) => {
    if (!list.length) throw new Error(`the demo has no ${name}: run make demo`);
    return list[0].id;
  };
  const timeout = errors.items.find((g) => g.exception_type === "PaymentGatewayTimeout");
  const done = investigations.find((i) => i.status === "completed");
  return {
    project: store.id,
    error: timeout?.id ?? pick(errors.items, "error groups"),
    investigation: done?.id ?? pick(investigations, "investigations"),
    alert: (alerts.find((a) => a.state === "firing") ?? alerts[0])?.id ?? pick(alerts, "alert rules"),
  };
}

function resolve(p, ids) {
  return p.replace(/:([a-z]+)/g, (_, k) => ids[k] ?? `:${k}`);
}

async function visit(browser, { role, token, page: pagePath, url, theme, sizeKey, projectId }) {
  const ctx = await browser.createBrowserContext();
  if (token) await ctx.setCookie({ name: COOKIE, value: token, url: BASE, httpOnly: true, sameSite: "Lax" });
  const page = await ctx.newPage();
  await page.setViewport(SIZES[sizeKey]);
  await page.evaluateOnNewDocument(
    (t, projectId) => {
      try {
        localStorage.setItem("theme", t);
        if (projectId) localStorage.setItem("logmind.ui", JSON.stringify({ state: { sidebarCollapsed: false, projectId }, version: 1 }));
      } catch {
        // Storage may be blocked; the page then follows the system theme.
      }
    },
    theme,
    projectId ?? ""
  );
  const problems = [];
  page.on("console", (m) => {
    if (m.type() !== "error") return;
    problems.push(`console: ${m.text().slice(0, 240)}`);
  });
  page.on("pageerror", (e) => problems.push(`page error: ${String(e).slice(0, 240)}`));
  page.on("response", (r) => {
    const u = r.url();
    if (!u.startsWith(BASE) || r.status() < 400) return;
    problems.push(`HTTP ${r.status()} ${r.request().method()} ${u.replace(BASE, "")}`);
  });
  page.on("requestfailed", (r) => {
    const u = r.url();
    // Navigations cancel in-flight prefetches and the live socket closes with the page.
    if (/\/ws\/|_rsc=|webpack-hmr/.test(u) || r.failure()?.errorText === "net::ERR_ABORTED") return;
    problems.push(`request failed: ${u.replace(BASE, "")} ${r.failure()?.errorText ?? ""}`);
  });
  try {
    await page.goto(url, { waitUntil: "networkidle2", timeout: 60_000 });
  } catch (e) {
    problems.push(`navigation: ${e.message}`);
  }
  // Live views keep a socket open, so "network idle" can come before the data renders:
  // wait for every loading placeholder to go away.
  await page.waitForFunction(() => !document.querySelector("[aria-busy=true],[aria-busy='']"), { timeout: 20_000 }).catch(() => {});
  await sleep(500);
  const checks = await page.evaluate(() => {
    const doc = document.documentElement;
    const broken = [...document.images].filter((i) => i.complete && i.naturalWidth === 0).map((i) => i.src);
    const errorStates = [...document.querySelectorAll("[data-qa=error-state]")].map((e) => e.textContent?.trim().slice(0, 160));
    const main = document.querySelector("main") ?? document.body;
    const busy = !!document.querySelector("[aria-busy=true],[aria-busy='']");
    return {
      overflow: doc.scrollWidth - doc.clientWidth,
      broken,
      errorStates,
      mainText: (main.innerText ?? "").trim().length,
      busy,
      path: location.pathname,
    };
  });
  if (checks.overflow > 1) problems.push(`horizontal overflow of ${checks.overflow}px`);
  for (const b of checks.broken) problems.push(`broken image ${b}`);
  for (const e of checks.errorStates) problems.push(`error state: ${e}`);
  if (checks.mainText < 40) problems.push(`page looks empty (${checks.mainText} characters of text)`);
  if (checks.busy) problems.push("still loading after the network went idle");
  if (role !== "anonymous" && checks.path === "/login") problems.push("sent to sign in: the session was refused");
  const file = path.join(OUT, `${role}-${slug(pagePath)}-${theme}-${sizeKey}.png`);
  await page.screenshot({ path: file, fullPage: true });
  await ctx.close();
  return problems;
}

async function main() {
  await mkdir(OUT, { recursive: true });
  const tokens = { anonymous: null };
  for (const role of ROLES) if (role !== "anonymous") tokens[role] = await signIn(EMAIL, PASSWORD);
  const ids = await resolveIds(tokens.owner ?? (await signIn(EMAIL, PASSWORD)));
  const browser = await puppeteer.launch({ headless: true, executablePath: CHROME, args: ["--no-sandbox"] });
  const failures = [];
  let visited = 0;
  try {
    for (const role of ROLES) {
      for (const p of ROLE_PAGES[role] ?? []) {
        if (ONLY && !ONLY.has(p)) continue;
        for (const theme of THEMES) {
          for (const sizeKey of SIZE_KEYS) {
            const url = `${BASE}${resolve(p, ids)}`;
            const problems = await visit(browser, { role, token: tokens[role], page: p, url, theme, sizeKey, projectId: ids.project });
            visited++;
            const tag = `${role} ${p} [${theme} ${sizeKey}]`;
            if (problems.length) {
              failures.push({ tag, problems: [...new Set(problems)] });
              console.log(`FAIL ${tag}`);
              for (const pr of new Set(problems)) console.log(`     ${pr}`);
            } else {
              console.log(`ok   ${tag}`);
            }
          }
        }
      }
    }
  } finally {
    await browser.close();
  }
  console.log(`\n${visited} page views, ${failures.length} with problems. Screenshots in ${OUT}`);
  if (failures.length) process.exit(1);
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
