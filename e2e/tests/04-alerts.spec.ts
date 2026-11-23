import { expect, test } from "@playwright/test";

import { apiAs, createProjectAndKey, eventually, MAILPIT, projectClient, scopeTo, sendLogs, unique } from "../helpers";

test("A9: a threshold rule fires on live data and the email reaches Mailpit", async ({ page, request }) => {
  const admin = await apiAs();
  const { project, key } = await createProjectAndKey(admin);
  const client = await projectClient(key);
  const to = `${unique("oncall")}@lumen.example`;
  await scopeTo(page, project.id);

  await page.goto("/alerts");
  await page.getByTestId("new-alert").click();
  await page.getByLabel("Name").fill("Checkout errors (e2e)");
  await page.getByLabel("Service").fill("checkout");
  await page.getByLabel("Above").fill("2");
  await page.getByLabel("Email").fill(to);
  await page.getByRole("button", { name: "Create rule" }).click();
  await expect(page.getByRole("row").filter({ hasText: "Checkout errors (e2e)" })).toBeVisible();

  await sendLogs(client, Array.from({ length: 5 }, (_, i) => ({ message: `checkout failed ${i}`, level: "error", service: "checkout" })));

  const mail = await eventually(async () => {
    const r = await request.get(`${MAILPIT}/api/v1/search?query=${encodeURIComponent(`to:${to}`)}`);
    const body = (await r.json()) as { messages_count: number; messages: { Subject: string }[] };
    return body.messages_count > 0 ? body.messages[0] : null;
  }, 90_000);
  expect(mail.Subject).toContain("FIRING: Checkout errors (e2e)");

  await page.reload();
  await expect(page.getByTestId("alert-history")).toContainText("Checkout errors (e2e)");
  await expect(page.getByTestId("alert-history")).toContainText("email delivered");
});
