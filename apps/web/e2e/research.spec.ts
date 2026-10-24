import { expect, type Page, test } from "@playwright/test";

import { login } from "./helpers";

// RESEARCH-10: admitted account -> Research (UI) -> durable job -> worker -> fixture source document -> proposed,
// excerpt-anchored claims -> reviewer acceptance -> source-supported fact. Synthetic data; nothing is sent.

test.describe.configure({ mode: "serial" });

const SCHOOL = "Crescent Valley Grammar School (Synthetic)";
const EXCERPT = "We operate two campuses in Lahore, in Johar Town and DHA.";

async function openResearchedAccount(page: Page) {
  await page.goto("/discovery");
  await page.getByRole("table", { name: "Discovery runs, newest first" }).getByRole("link").first().click();
  const card = page.getByRole("article", { name: `Listing ${SCHOOL}` }).filter({ hasText: "Johar Town" });
  await card.getByRole("link", { name: "open account" }).click();
  await expect(page.getByRole("heading", { level: 1, name: SCHOOL })).toBeVisible();
}

test("RESEARCH-10 operator researches an admitted account and accepts one excerpt-backed claim", async ({ page }) => {
  await login(page, "operator");
  await page.goto("/discovery");
  await page.getByRole("table", { name: "Discovery runs, newest first" }).getByRole("link").first().click();
  const card = page.getByRole("article", { name: `Listing ${SCHOOL}` }).filter({ hasText: "Johar Town" });
  await card.getByRole("button", { name: "Accept as new campus" }).click();
  await expect(card.getByText(/review: accepted/)).toBeVisible();
  await card.getByRole("link", { name: "open account" }).click();
  await expect(page.getByRole("heading", { level: 1, name: SCHOOL })).toBeVisible();

  const research = page.locator("section").filter({ has: page.getByRole("heading", { name: "Research (proposed claims need review)" }) });
  await expect(research.getByText("No research has been run for this account.")).toBeVisible();
  await research.getByLabel("fixture_lahore_schools (full_allowed)").check();
  await research.getByRole("button", { name: "Run research" }).click();
  await expect(research.getByRole("status").filter({ hasText: "Completed: 6 proposed claims from 1 source(s)" })).toBeVisible({
    timeout: 60_000,
  });
  await expect(research.getByText(/2 statement\(s\) skipped as negated, instruction-like or over budget/)).toBeVisible();
  await expect(research.getByText(/ignore previous instructions/i)).toHaveCount(0);
  await expect(research.getByText(/40 campuses|Excel/)).toHaveCount(0);

  const claim = research.getByRole("article", { name: "Research claim campus_count" });
  await expect(claim.getByText("Proposed (not verified)")).toBeVisible();
  await expect(claim.getByText(EXCERPT)).toBeVisible();
  await expect(claim.getByRole("link", { name: /^https:\/\/school\.fixture\.example\// })).toBeVisible();
  await expect(page.getByRole("heading", { name: "campus_count: count: 2" })).toHaveCount(1); // only the proposal

  await claim.getByRole("button", { name: "Accept claim" }).click();
  await expect(claim.getByText("Accepted by a reviewer (now a fact)")).toBeVisible();
  const evidence = page.locator("section").filter({ has: page.getByRole("heading", { name: "Evidence (current, source-supported)" }) });
  await expect(evidence.getByRole("heading", { name: "campus_count: count: 2" })).toBeVisible();
  await expect(evidence.getByText("Source-supported", { exact: true })).toBeVisible();
  await expect(evidence.getByText(EXCERPT)).toBeVisible();
  await expect(page.getByText("account.fact_added", { exact: false })).toBeVisible();
});

test("RESEARCH-10 observer sees research read-only", async ({ page }) => {
  await login(page, "observer");
  await openResearchedAccount(page);
  const research = page.locator("section").filter({ has: page.getByRole("heading", { name: "Research (proposed claims need review)" }) });
  await expect(research.getByRole("article").first()).toBeVisible();
  await expect(research.getByRole("button")).toHaveCount(0);
});

test("RESEARCH-10 accepted claim and fact survive an api/web restart @after-restart", async ({ page }) => {
  await login(page, "operator");
  await openResearchedAccount(page);
  const research = page.locator("section").filter({ has: page.getByRole("heading", { name: "Research (proposed claims need review)" }) });
  await expect(research.getByRole("article", { name: "Research claim campus_count" }).getByText("Accepted by a reviewer (now a fact)")).toBeVisible();
  const evidence = page.locator("section").filter({ has: page.getByRole("heading", { name: "Evidence (current, source-supported)" }) });
  await expect(evidence.getByText(EXCERPT)).toBeVisible();
});
