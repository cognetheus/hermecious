import { expect, type Page, test } from "@playwright/test";

import { login } from "./helpers";

// SCHOOL-10: P1.4 account + P3.1 accepted claim -> generated six-key brief in the UI -> reload/restart.
// Runs after research.spec.ts, which admitted the Johar Town listing and accepted its "two campuses" claim.

test.describe.configure({ mode: "serial" });

const SCHOOL = "Crescent Valley Grammar School (Synthetic)";
const KEYS = ["Campus footprint", "Operator autonomy", "Admissions workflow", "Fee process", "Public contact route", "Operational complexity"];

async function openAccount(page: Page) {
  await page.goto("/discovery");
  await page.getByRole("table", { name: "Discovery runs, newest first" }).getByRole("link").first().click();
  const card = page.getByRole("article", { name: `Listing ${SCHOOL}` }).filter({ hasText: "Johar Town" });
  await card.getByRole("link", { name: "open account" }).click();
  await expect(page.getByRole("heading", { level: 1, name: SCHOOL })).toBeVisible();
  return page.locator("section").filter({ has: page.getByRole("heading", { name: "School Research" }) });
}

test("SCHOOL-10 operator generates a cited six-part brief with no ranking", async ({ page }) => {
  await login(page, "operator");
  const section = await openAccount(page);
  await expect(section.getByText("No brief has been generated yet.")).toBeVisible();
  await section.getByRole("button", { name: "Generate school brief" }).click();
  await expect(section.getByText("Brief generated")).toBeVisible();
  for (const key of KEYS) {
    await expect(section.getByRole("article", { name: `Signal ${key}` })).toBeVisible();
  }
  const campus = section.getByRole("article", { name: "Signal Campus footprint" });
  await expect(campus.getByText("Observed (cited source)")).toBeVisible();
  await expect(campus.getByText("A cited source states: 2 campuses.")).toBeVisible();
  await expect(campus.getByRole("list", { name: "Citations" }).getByRole("link", { name: /^https:\/\/school\.fixture\.example\// })).toBeVisible();
  await expect(campus.getByText(/Discovery question: How many campuses does the school run/)).toBeVisible();
  const autonomy = section.getByRole("article", { name: "Signal Operator autonomy" });
  await expect(autonomy.getByText("Unknown", { exact: true })).toBeVisible();
  await expect(section.getByText(/score|priority|qualified|ranking/i)).toHaveCount(1); // only the "does not score, rank or qualify" notice

  await section.getByRole("button", { name: "Generate school brief" }).click();
  await expect(section.getByText("No evidence changed: the existing brief is current")).toBeVisible();
  await page.reload();
  await expect(section.getByRole("article", { name: "Signal Campus footprint" }).getByText("A cited source states: 2 campuses.")).toBeVisible();
});

test("SCHOOL-10 observer reads the brief without a generate control", async ({ page }) => {
  await login(page, "observer");
  const section = await openAccount(page);
  await expect(section.getByRole("article", { name: "Signal Fee process" })).toBeVisible();
  await expect(section.getByRole("button")).toHaveCount(0);
});

test("SCHOOL-10 brief survives an api/web restart @after-restart", async ({ page }) => {
  await login(page, "operator");
  const section = await openAccount(page);
  await expect(section.getByRole("article", { name: "Signal Campus footprint" }).getByText("Observed (cited source)")).toBeVisible();
});
