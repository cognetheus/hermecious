import { expect, test } from "@playwright/test";

import { apiPost, login } from "./helpers";

// P5.3 diagnostics in the default `simulation` mode (the E2E stack never has Meta credentials): the page is
// read-only, offers no way to send, and the API refuses the owner-only actions. The owner-confirmed real test
// send itself is covered offline by WATEST-01..09 and is BLOCKED_EXTERNAL live (WATEST-10).

test("WATEST-UI owner sees the test connection fail closed in simulation mode", async ({ page }) => {
  await login(page, "owner");
  await page.getByRole("link", { name: "WhatsApp test" }).click();
  await expect(page.getByRole("heading", { level: 1, name: "WhatsApp test connection" })).toBeVisible();
  const status = page.getByRole("list", { name: "Connection status" });
  await expect(status.getByText("Mode: simulation")).toBeVisible();
  await expect(status.getByText("Test sending: unavailable in this mode")).toBeVisible();
  await expect(page.getByRole("note")).toContainText("Production outreach is off");
  await expect(page.getByRole("button", { name: "Sync templates from Meta" })).toHaveCount(0);
  await expect(page.getByRole("form", { name: "Preview a test message" })).toHaveCount(0);
  await expect(page.getByRole("button", { name: /send/i })).toHaveCount(0);
  expect(await apiPost(page, "/api/v1/integrations/whatsapp/templates/sync", {})).toBe(409);
  expect(
    await apiPost(page, "/api/v1/integrations/whatsapp/test-sends", { recipient_id: crypto.randomUUID(), phone_number: "+923001234567" }),
  ).toBe(422);
});

test("WATEST-UI observer gets read-only status and no controls", async ({ page }) => {
  await login(page, "observer");
  await page.goto("/integrations/whatsapp");
  await expect(page.getByRole("heading", { level: 1, name: "WhatsApp test connection" })).toBeVisible();
  await expect(page.getByRole("button")).toHaveCount(0);
  expect(await apiPost(page, "/api/v1/integrations/whatsapp/templates/sync", {})).toBe(403);
});
