import { expect, test } from "@playwright/test";

import { apiAs, createProjectAndKey, projectClient, scopeTo, sendLogs } from "../helpers";

const stack = (line: number) => `TypeError: Cannot read properties of undefined (reading 'price')
    at renderResults (/srv/search/src/render.js:${line}:17)
    at handle (/srv/search/src/handler.js:88:9)`;

test("A2: similar stack traces become one error group with first and last seen", async ({ page }) => {
  const admin = await apiAs();
  const { project, key } = await createProjectAndKey(admin);
  const client = await projectClient(key);
  for (const line of [31, 47, 90]) {
    await sendLogs(client, [{ message: "render failed", level: "error", service: "search", exception: { type: "", stacktrace: stack(line) } }]);
  }
  await scopeTo(page, project.id);
  await page.goto("/errors");
  const row = page.getByRole("row").filter({ hasText: "TypeError" });
  await expect(row).toHaveCount(1);
  await expect(row).toContainText("3");
  await expect(row).toContainText("renderResults (render.js)");
  await row.getByRole("link").click();
  await expect(page.getByRole("heading", { level: 1 })).toContainText("TypeError");
  await expect(page.getByText("Every line with this fingerprint")).toBeVisible();
  await page.getByRole("button", { name: "Resolve" }).click();
  await expect(page.getByText("Marked resolved.")).toBeVisible();
});
