import { expect, test } from "@playwright/test";

import { apiPost, login } from "./helpers";

// RELEASE-10 (P5.5) in the browser: the E2E stack is a test deployment with no Meta credentials, no real audit
// and no attestations, so the go/no-go review must say NO GO, offer no pilot or send control, and refuse a pilot
// send through the API. No request can reach Meta.

test("RELEASE-10 owner sees NO GO, the persistent banner and no way to send", async ({ page }) => {
  const egress: string[] = [];
  await page.route(/graph\.facebook\.com|facebook\.com|whatsapp\.(com|net)/, (route) => {
    egress.push(route.request().url());
    return route.abort();
  });
  await login(page, "owner");
  await page.getByRole("link", { name: "Production readiness" }).click();
  await expect(page.getByRole("heading", { level: 1, name: "WhatsApp Production Readiness" })).toBeVisible();
  await expect(page.getByRole("note")).toHaveText("PRODUCTION OUTBOUND DISABLED UNTIL SEPARATE OPERATOR GO-LIVE");
  await expect(page.getByText(/Deploy-time live gate: closed/)).toBeVisible();
  await page.getByRole("button", { name: "Evaluate readiness now" }).click();
  await expect(page.getByRole("status").filter({ hasText: "NO GO" })).toBeVisible();
  const checks = page.getByRole("table", { name: "Prerequisites" });
  await expect(checks.getByRole("row").filter({ hasText: "school evidence audit" })).toContainText("FAILED");
  await expect(checks.getByRole("row").filter({ hasText: "pakistan legal review" })).toContainText("BLOCKED_EXTERNAL");
  await expect(page.getByRole("form", { name: "Authorize a pilot" })).toHaveCount(0);
  await expect(page.getByRole("button", { name: /send|bulk|campaign/i })).toHaveCount(0);
  const preview = await apiPost(page, "/api/v1/release/whatsapp/pilot-sends", {
    draft_id: crypto.randomUUID(),
    parameters: [],
    idempotency_key: "e2e-pilot-0001",
  });
  expect(preview).toBe(409);
  expect(await apiPost(page, "/api/v1/release/whatsapp/pilot-sends", { draft_id: crypto.randomUUID(), phone_number: "+923001234567" })).toBe(422);
  expect(egress).toEqual([]);
});

test("RELEASE-10 observer cannot open the readiness review", async ({ page }) => {
  await login(page, "observer");
  await page.goto("/release/whatsapp");
  await expect(page.getByText("Production readiness is available to owners and operators only.")).toBeVisible();
});
