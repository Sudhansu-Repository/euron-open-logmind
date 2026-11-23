import { expect, test } from "@playwright/test";

import { apiAs, createProjectAndKey, projectClient, scopeTo, sendLogs, unique } from "../helpers";

test("A7: PII and secrets are redacted before storage, and the policy is previewable", async ({ page }) => {
  const admin = await apiAs();
  const { project, key } = await createProjectAndKey(admin);
  const client = await projectClient(key);
  const marker = unique("pii");
  const result = await sendLogs(client, [{ message: `reset for jane.doe@example.com card 4111 1111 1111 1111 ${marker}`, service: "auth" }]);
  expect(result.redactions).toBe(2);
  await scopeTo(page, project.id);
  await page.goto(`/logs?q=${marker}`);
  const list = page.getByTestId("log-list");
  await expect(list).toContainText("[REDACTED:email]");
  await expect(list).toContainText("[REDACTED:payment_card]");
  await expect(list).not.toContainText("jane.doe@example.com");

  await page.goto("/settings?tab=projects");
  await page.getByRole("button", { name: "Preview redaction" }).click();
  await expect(page.getByTestId("redaction-preview")).toContainText("[REDACTED:email]");
});

test("API keys are shown once and revocable from Settings", async ({ page }) => {
  const admin = await apiAs();
  const { project } = await createProjectAndKey(admin);
  await scopeTo(page, project.id);
  await page.goto("/settings?tab=keys");
  await page.getByLabel("Key name").fill("ci runner");
  await page.getByTestId("create-key").click();
  await expect(page.getByText("Your new API key")).toBeVisible();
  await expect(page.getByTestId("one-time-secret")).toHaveText(/^lmk_[0-9a-f]{12}_/);
  await page.keyboard.press("Escape");
  const row = page.getByRole("row").filter({ hasText: "ci runner" });
  await row.getByRole("button", { name: "Revoke" }).click();
  await page.getByRole("button", { name: "Revoke key" }).click();
  await expect(page.getByText("Key revoked.")).toBeVisible();
  await expect(page.getByRole("row").filter({ hasText: "ci runner" })).toHaveCount(0);
});
