import { defineConfig, devices } from "@playwright/test";

/**
 * Browser end-to-end tests against the running local stack (`make up && make demo`): the
 * dashboard, the API, the worker (AI investigations, alerts), Postgres, Redis, ClickHouse,
 * the mock AI service, Mailpit and, on Floci, S3 and KMS.
 *
 *   pnpm test                 every suite
 *   E2E_HEADED=1 pnpm test    watch it
 *
 * Every suite creates its own project with a per-run suffix, so reruns pass on the same
 * seeded stack. The suites share one
 * organization (the demo owner), so they run in a single worker, in file order.
 */
export default defineConfig({
  testDir: "./tests",
  globalSetup: "./global-setup.ts",
  fullyParallel: false,
  workers: 1,
  retries: 0,
  timeout: 180_000,
  expect: { timeout: 20_000 },
  reporter: [["list"], ["html", { outputFolder: "playwright-report", open: "never" }]],
  outputDir: "test-results",
  use: {
    baseURL: process.env.WEB_URL || "http://localhost:6010",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    headless: !process.env.E2E_HEADED,
    storageState: ".auth/owner.json",
    viewport: { width: 1440, height: 900 },
    acceptDownloads: true,
    // The dashboard marks testable elements with data-qa (the QA sweep reads the same).
    testIdAttribute: "data-qa",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"], viewport: { width: 1440, height: 900 } } }],
});
