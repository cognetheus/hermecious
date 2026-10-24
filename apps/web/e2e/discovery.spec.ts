import { expect, type Page, test } from "@playwright/test";

import { login } from "./helpers";

// RUN-10 (and the UI half of RUN-09): browser -> API -> durable job -> worker -> offline fixture source ->
// staged listings -> reviewer admission -> P1.4 account. The fixture is synthetic; nothing is sent anywhere.

test.describe.configure({ mode: "serial" });

const GULBERG = "Gulberg Science School (Synthetic)";

async function latestRun(page: Page) {
  await page.goto("/discovery");
  await page.getByRole("table", { name: "Discovery runs, newest first" }).getByRole("link").first().click();
}

test("RUN-10 operator starts a bounded fixture run, reviews evidence and admits one campus", async ({ page }) => {
  await login(page, "operator");
  await page.getByRole("link", { name: "Discovery" }).click();
  await expect(page.getByRole("heading", { level: 1, name: "Discovery runs" })).toBeVisible();
  await page.getByRole("link", { name: "New discovery run" }).click();

  const form = page.getByRole("form", { name: "New discovery run" });
  await expect(form.getByLabel("Source", { exact: true })).toHaveValue("fixture_lahore_schools");
  await expect(form.getByText("Synthetic fixture: fictional records, not real Lahore schools.")).toBeVisible();
  await expect(form.getByText(/there is no free-form area or map box/)).toBeVisible();
  await expect(form.getByLabel("Maximum listings", { exact: true })).toHaveAttribute("max", "30");
  await form.getByLabel("Maximum listings", { exact: true }).fill("10");
  await form.getByLabel("Seconds", { exact: true }).fill("30");
  await form.getByRole("button", { name: "Start run" }).focus();
  await page.keyboard.press("Enter"); // keyboard-operable submit

  await expect(page.getByRole("heading", { level: 1, name: "Discovery run" })).toBeVisible();
  await expect(page.getByRole("status").filter({ hasText: "Status: Completed (bounded run)" })).toBeVisible({
    timeout: 60_000,
  });
  await expect(page.getByText("examined 9; staged 4; rejected by rules 5; shown 4 (maximum 10)")).toBeVisible();
  await expect(page.getByText("This run is bounded and is not a complete list of schools in Lahore.")).toBeVisible();
  await expect(page.getByRole("article")).toHaveCount(4);

  const card = page.getByRole("article", { name: `Listing ${GULBERG}` });
  await expect(card.getByText("Unverified listing")).toBeVisible();
  await expect(card.getByText(/Unknown \(not researched\): ownership, campus_count, decision_authority/)).toBeVisible();
  await expect(card.getByRole("link", { name: "source record" })).toHaveAttribute("href", /^https:\/\//);
  await card.getByLabel("Review reason", { exact: true }).fill("Checked the listing and its source page");
  await card.getByRole("button", { name: "Accept as new campus" }).click();
  await expect(card.getByText(/review: accepted/)).toBeVisible();
  await expect(card.getByRole("button", { name: "Accept as new campus" })).toHaveCount(0);

  await card.getByRole("link", { name: "open account" }).click();
  await expect(page.getByRole("heading", { level: 1, name: GULBERG })).toBeVisible();
  await expect(page.getByText(/status discovered; version 1/)).toBeVisible();
  await expect(page.getByText(/qualified/i)).toHaveCount(0);
});

test("RUN-09 observer sees the run read-only with escaped text and no review controls", async ({ page }) => {
  await login(page, "observer");
  await page.goto("/discovery");
  await expect(page.getByRole("link", { name: "New discovery run" })).toHaveCount(0);
  await latestRun(page);
  await expect(page.getByRole("article")).toHaveCount(4);
  await expect(page.getByRole("button")).toHaveCount(0); // no review, match or cancel controls for observers
  await expect(page.getByText("Synthetic fixture data: fictional records, not real Lahore schools.")).toBeVisible();
  const status = await page.evaluate(async () => {
    const csrf = (await (await fetch("/api/v1/auth/csrf")).json()).csrf_token as string;
    const response = await fetch("/api/v1/discovery/runs", {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-CSRF-Token": csrf },
      body: JSON.stringify({ provider: "fixture_lahore_schools", idempotency_key: "observer-attempt-1" }),
    });
    return response.status;
  });
  expect(status).toBe(403);
});

test("RUN-09 accepted review and account survive an api/web restart @after-restart", async ({ page }) => {
  await login(page, "operator");
  await latestRun(page);
  await expect(page.getByRole("status").filter({ hasText: "Status: Completed (bounded run)" })).toBeVisible();
  const card = page.getByRole("article", { name: `Listing ${GULBERG}` });
  await expect(card.getByText(/review: accepted/)).toBeVisible();
  await expect(page.getByText("1 accepted; 0 rejected; 0 deferred; 3 pending")).toBeVisible();
  await card.getByRole("link", { name: "open account" }).click();
  await expect(page.getByRole("heading", { level: 1, name: GULBERG })).toBeVisible();
});
