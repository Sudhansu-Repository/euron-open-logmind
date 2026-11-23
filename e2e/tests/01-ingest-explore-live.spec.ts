import { expect, test } from "@playwright/test";

import { apiAs, createProjectAndKey, projectClient, scopeTo, sendLogs, unique, watchConsole } from "../helpers";

test("A1, A6: lines sent over the API and OTLP show up live and in the explorer", async ({ page }) => {
  const admin = await apiAs();
  const { project, key } = await createProjectAndKey(admin);
  const client = await projectClient(key);
  const errors = watchConsole(page);
  await scopeTo(page, project.id);

  await page.goto("/live");
  await expect(page.getByRole("heading", { name: "Live logs" })).toBeVisible();
  await expect(page.getByText("Streaming")).toBeVisible();
  const marker = unique("hello");
  await sendLogs(client, [{ message: `checkout started ${marker}`, service: "checkout", attributes: { cart: { items: 3 } } }]);
  await expect(page.getByTestId("live-list").getByText(`checkout started ${marker}`)).toBeVisible({ timeout: 10_000 });

  // OTLP/JSON, the shape any OpenTelemetry exporter sends to /v1/logs.
  const otlpMarker = unique("otlp");
  const otlp = await client.post("/v1/logs", {
    headers: { "content-type": "application/json" },
    data: {
      resourceLogs: [
        {
          resource: { attributes: [{ key: "service.name", value: { stringValue: "inventory" } }] },
          scopeLogs: [{ logRecords: [{ timeUnixNano: String(Date.now() * 1_000_000), severityNumber: 13, severityText: "WARN", body: { stringValue: `stock low ${otlpMarker}` } }] }],
        },
      ],
    },
  });
  expect(otlp.status()).toBe(200);

  await page.goto(`/logs?q=${encodeURIComponent(otlpMarker)}`);
  const list = page.getByTestId("log-list");
  await expect(list.getByText(`stock low ${otlpMarker}`)).toBeVisible();
  await page.goto(`/logs?q=${encodeURIComponent(marker)}`);
  await list.getByText(`checkout started ${marker}`).click();
  await expect(page.getByTestId("log-message")).toContainText(marker);
  await expect(page.getByText('"items": 3')).toBeVisible();
  expect(errors).toEqual([]);
});

test("the explorer filters by level and service", async ({ page }) => {
  const admin = await apiAs();
  const { project, key } = await createProjectAndKey(admin);
  const client = await projectClient(key);
  await sendLogs(client, [
    { message: "auth ok", service: "auth" },
    { message: "auth failed for user 7", service: "auth", level: "error" },
    { message: "search ok", service: "search" },
  ]);
  await scopeTo(page, project.id);
  await page.goto("/logs?level=error");
  await expect(page.getByTestId("log-list").getByTestId("log-row")).toHaveCount(1);
  await expect(page.getByTestId("log-list")).toContainText("auth failed for user 7");
  await page.goto("/logs?service=search");
  await expect(page.getByTestId("log-list")).toContainText("search ok");
  await expect(page.getByTestId("log-list")).not.toContainText("auth ok");
});
