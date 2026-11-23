import { expect, test } from "@playwright/test";

import { apiAs, call, createProjectAndKey, incident, projectClient, scopeTo, sendLogs } from "../helpers";

test("A3, A4, A11, A12: an investigation cites real lines, verifies them and answers a follow-up", async ({ page }) => {
  const admin = await apiAs();
  const providers = await call<{ enabled: boolean }[]>(admin, "GET", "/api/v1/ai/providers");
  expect(providers.some((p) => p.enabled), "make demo configures the mock provider").toBe(true);
  const { project, key } = await createProjectAndKey(admin);
  const client = await projectClient(key);
  await sendLogs(client, incident());
  await scopeTo(page, project.id);

  await page.goto("/errors");
  await page.getByRole("row").filter({ hasText: "PaymentGatewayTimeout" }).getByRole("link").click();
  await page.getByTestId("investigate").click();
  await expect(page).toHaveURL(/\/investigations\//);

  const rootCause = page.getByTestId("root-cause");
  await expect(rootCause).toContainText("pool", { timeout: 60_000 });
  await expect(rootCause).toContainText("v9.1.0");
  await expect(page.getByText("Grounded").first()).toBeVisible();
  // Compression is visible: many lines in, a handful of evidence items out.
  await expect(page.getByText("Lines in the window")).toBeVisible();
  await expect(page.getByText("Left out by selection")).toBeVisible();

  const evidence = page.getByTestId("evidence-list");
  await expect(evidence).toContainText("db connection pool exhausted");
  await rootCause.getByTestId("citation").first().click();
  await page.getByTestId("verify").click();
  await expect(page.getByTestId("verify-result")).toContainText(/All \d+ cited lines were re-read/);

  // A cited line opens as the real stored line.
  await evidence.getByText("deploy started: payments version v9.1.0").click();
  await expect(page.getByTestId("log-message")).toContainText("deploy started: payments version v9.1.0");
  await page.keyboard.press("Escape");

  await page.getByTestId("followup-input").fill("What changed before this started?");
  await page.getByRole("button", { name: "Ask" }).click();
  const answer = page.getByTestId("followup").last();
  await expect(answer).toContainText("change event", { timeout: 60_000 });
  await expect(answer.getByTestId("citation").first()).toBeVisible();
});
