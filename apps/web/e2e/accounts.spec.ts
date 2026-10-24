import { expect, test } from "@playwright/test";

import { apiPost, createAccount, login, RUN } from "./helpers";

const SCHOOL = `Crescent Valley Grammar School ${RUN} (Synthetic)`;

test.describe.configure({ mode: "serial" });

test("ACCOUNT-01 operator creates a Lahore school and it persists across reloads", async ({ page }) => {
  await login(page, "operator");
  await createAccount(page, SCHOOL);
  await expect(page.getByText("Lahore, Johar Town; status discovered; version 1")).toBeVisible();
  await page.reload();
  await expect(page.getByRole("heading", { level: 1, name: SCHOOL })).toBeVisible();
  await page.goto(`/accounts?q=${encodeURIComponent("Crescent Valley Grammar School " + RUN)}`);
  await expect(page.getByRole("link", { name: SCHOOL })).toBeVisible();
});

test("ACCOUNT-02 source-supported fact shows source, time, rights and verification", async ({ page }) => {
  await login(page, "operator");
  await page.goto(`/accounts?q=${encodeURIComponent("Crescent Valley Grammar School " + RUN)}`);
  await page.getByRole("link", { name: SCHOOL }).click();
  const form = page.locator("form").filter({ has: page.getByRole("button", { name: "Record fact" }) });
  await form.getByLabel("Claim type", { exact: true }).selectOption("campus_count");
  await form.getByLabel("Value (JSON)", { exact: true }).fill('{"count": 2}');
  await form.getByLabel("Verification", { exact: true }).selectOption("source_supported");
  await form.getByLabel("Confidence", { exact: true }).selectOption("moderate");
  await form.getByLabel("Evidence excerpt (needs full storage rights)", { exact: true }).fill("Admissions open at both of our campuses.");
  await form.getByLabel("Register a source (not fetched)", { exact: true }).check();
  await form.getByLabel("Provider", { exact: true }).selectOption("first_party_website");
  await form.getByLabel("Storage rights", { exact: true }).selectOption("full_allowed");
  await form.getByLabel("Source URL", { exact: true }).fill("https://crescent-valley.example/admissions");
  await form.getByRole("button", { name: "Record fact" }).click();
  await expect(page.getByRole("status").filter({ hasText: "Fact recorded" })).toBeVisible();
  await page.reload();
  const evidence = page.locator("section").filter({ has: page.getByRole("heading", { name: "Evidence (current, source-supported)" }) });
  await expect(evidence.getByRole("heading", { name: "campus_count: count: 2" })).toBeVisible();
  await expect(evidence.getByText("Source-supported", { exact: true })).toBeVisible();
  await expect(evidence.getByText("https://crescent-valley.example/admissions")).toBeVisible();
  await expect(evidence.getByText(/full_allowed, rights-2026-10-23/)).toBeVisible();
  await expect(evidence.getByText(/\(Asia\/Karachi\)/)).toBeVisible();
  await expect(evidence.getByText("Admissions open at both of our campuses.")).toBeVisible();
});

test("ACCOUNT-03 unknown ERP is shown as an unverified hypothesis, never as absence", async ({ page }) => {
  await login(page, "operator");
  await page.goto(`/accounts?q=${encodeURIComponent("Crescent Valley Grammar School " + RUN)}`);
  await page.getByRole("link", { name: SCHOOL }).click();
  const form = page.locator("form").filter({ has: page.getByRole("button", { name: "Record fact" }) });
  await form.getByLabel("Claim type", { exact: true }).selectOption("software_in_use");
  await form.getByLabel("Value (JSON)", { exact: true }).fill('{"status": "unknown"}');
  await form.getByLabel("Verification", { exact: true }).selectOption("hypothesis");
  await form.getByLabel("Confidence", { exact: true }).selectOption("unknown");
  await form.getByRole("button", { name: "Record fact" }).click();
  await expect(page.getByRole("status").filter({ hasText: "Fact recorded" })).toBeVisible();
  await page.reload();
  const hypotheses = page.locator("section").filter({ has: page.getByRole("heading", { name: "Hypotheses and unknowns (not verified)" }) });
  await expect(hypotheses.getByRole("heading", { name: "software_in_use: status: unknown" })).toBeVisible();
  await expect(hypotheses.getByText("Hypothesis (not verified)")).toBeVisible();
  await expect(hypotheses.getByText("No source: this is not verified evidence.")).toBeVisible();
  await expect(page.getByText(/no software|not used|none in use/i)).toHaveCount(0);
});

test("ACCOUNT-04 correction keeps history and leaves one current fact", async ({ page }) => {
  await login(page, "operator");
  await page.goto(`/accounts?q=${encodeURIComponent("Crescent Valley Grammar School " + RUN)}`);
  await page.getByRole("link", { name: SCHOOL }).click();
  const card = page.getByRole("article", { name: "campus_count fact" });
  await card.getByRole("button", { name: "Correct this fact" }).click();
  const form = card.getByRole("form", { name: "Correct campus_count" });
  await form.getByLabel("Reason (required)", { exact: true }).fill("Website now lists a third campus in Bahria Town");
  await form.getByLabel("Value (JSON)", { exact: true }).fill('{"count": 3}');
  await form.getByLabel("Verification", { exact: true }).selectOption("hypothesis");
  const saved = page.waitForResponse((r) => r.url().includes("/corrections") && r.request().method() === "POST");
  await form.getByRole("button", { name: "Record correction" }).click();
  expect((await saved).status()).toBe(201);
  await page.reload();
  const hypotheses = page.locator("section").filter({ has: page.getByRole("heading", { name: "Hypotheses and unknowns (not verified)" }) });
  await expect(hypotheses.getByRole("heading", { name: "campus_count: count: 3" })).toBeVisible();
  await expect(hypotheses.getByText("Correction reason: Website now lists a third campus in Bahria Town")).toBeVisible();
  const history = page.locator("section").filter({ has: page.getByRole("heading", { name: "Correction history" }) });
  await expect(history.getByText(/Superseded: campus_count: count: 2 \(Source-supported/)).toBeVisible();
  await expect(page.getByRole("heading", { name: /campus_count: count:/ })).toHaveCount(1);
  await expect(page.getByText("account.fact_corrected", { exact: false })).toBeVisible();
});

test("ACCOUNT-06 observer sees read-only detail without edit controls", async ({ page }) => {
  await login(page, "observer");
  await page.goto("/accounts");
  await expect(page.getByRole("link", { name: "New account" })).toHaveCount(0);
  await page.getByRole("link", { name: SCHOOL }).first().click();
  await expect(page.getByRole("heading", { level: 1, name: SCHOOL })).toBeVisible();
  await expect(page.getByRole("button")).toHaveCount(0);
  await expect(page.getByRole("form", { name: "Edit account" })).toHaveCount(0);
  await page.goto("/accounts/new");
  await expect(page).toHaveURL(/\/accounts$/);
});

test("ACCOUNT-09 markup in names renders as text and nothing executes @mobile", async ({ page }) => {
  let dialogs = 0;
  page.on("dialog", async (dialog) => {
    dialogs += 1;
    await dialog.dismiss();
  });
  await login(page, "operator");
  const hostile = `<img src=x onerror=alert(1)> ${RUN} <script>window.__pwned=1</script>`;
  await createAccount(page, hostile);
  await expect(page.getByRole("heading", { level: 1, name: hostile })).toBeVisible();
  expect(await page.evaluate(() => (window as unknown as { __pwned?: number }).__pwned)).toBeUndefined();
  expect(await page.locator("main img").count()).toBe(0);
  expect(dialogs).toBe(0);
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  expect(overflow).toBeLessThanOrEqual(1);
});

test("ACCOUNT-09 keyboard-only account creation", async ({ page }) => {
  await login(page, "operator");
  await page.goto("/accounts/new");
  await page.getByLabel("School name", { exact: true }).focus();
  await page.keyboard.type(`Keyboard Academy ${RUN} (Synthetic)`);
  await page.keyboard.press("Tab");
  await page.keyboard.type("Model Town");
  await page.keyboard.press("Enter");
  await expect(page.getByRole("heading", { level: 1, name: `Keyboard Academy ${RUN} (Synthetic)` })).toBeVisible();
});

test("list pagination and filters work through the UI", async ({ page }) => {
  await login(page, "operator");
  for (let i = 0; i < 26; i += 1) {
    expect(await apiPost(page, "/api/v1/accounts", { canonical_name: `Paged School ${RUN} ${String(i).padStart(2, "0")} (Synthetic)` })).toBe(201);
  }
  await page.goto(`/accounts?q=${encodeURIComponent(`Paged School ${RUN}`)}`);
  await expect(page.getByRole("row")).toHaveCount(26); // header + 25
  await page.getByRole("link", { name: "Next page" }).click();
  await expect(page.getByRole("row")).toHaveCount(2); // header + 1
  await expect(page.getByRole("link", { name: "Next page" })).toHaveCount(0);
  await page.goto(`/accounts?q=${encodeURIComponent(`Paged School ${RUN}`)}&status=researching`);
  await expect(page.getByText("No accounts match.")).toBeVisible();
});

test("@after-restart account, evidence and correction survive an API/web restart", async ({ page }) => {
  await login(page, "observer");
  await page.goto(`/accounts?q=${encodeURIComponent("Crescent Valley Grammar School " + RUN)}`);
  await page.getByRole("link", { name: SCHOOL }).click();
  await expect(page.getByRole("heading", { name: "campus_count: count: 3" })).toBeVisible();
  await expect(page.getByText(/Superseded: campus_count: count: 2/)).toBeVisible();
  await expect(page.getByRole("heading", { name: "software_in_use: status: unknown" })).toBeVisible();
});
