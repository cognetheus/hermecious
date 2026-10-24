import { expect, type Page, test } from "@playwright/test";

import { login, RUN } from "./helpers";

// CAMPAIGN-10: create -> preview -> approve for drafting (fixture mode: the real P3.4 gate is closed) -> exclude ->
// pause -> restart. Runs last (alphabetical) because it builds on the researched, assessed e2e account. No sends.

test.describe.configure({ mode: "serial" });

const SCHOOL = "Crescent Valley Grammar School (Synthetic)";
const OFFER = `school_core_${RUN.toLowerCase().replace(/[^a-z0-9_]/g, "")}`;
const NOTICE = "Channel permission not checked — do not contact from this screen.";
const NAME = `Lahore pilot ${RUN}`;

async function openCampaign(page: Page) {
  await page.goto("/campaigns");
  await page.getByRole("list", { name: "Campaigns" }).getByRole("link", { name: NAME }).click();
  await expect(page.getByRole("heading", { level: 1, name: NAME })).toBeVisible();
}

test("CAMPAIGN-10 operator plans a fixture campaign: preview, approve for drafting, exclude, pause", async ({ page }) => {
  await login(page, "operator");
  // Refresh the assessment (the evidence evaluation withdrew a fact, so the previous one is stale).
  await page.goto("/discovery");
  await page.getByRole("table", { name: "Discovery runs, newest first" }).getByRole("link").first().click();
  await page.getByRole("article", { name: `Listing ${SCHOOL}` }).filter({ hasText: "Johar Town" }).getByRole("link", { name: "open account" }).click();
  const qualification = page.locator("section").filter({ has: page.getByRole("heading", { name: "Qualification" }) });
  await qualification.getByLabel("Published offer", { exact: true }).selectOption({ label: OFFER });
  await qualification.getByRole("button", { name: "Assess account" }).click();
  await expect(qualification.getByText("Assessed", { exact: true })).toBeVisible();

  await page.goto("/");
  await page.getByRole("link", { name: "Campaigns" }).click();
  await expect(page.getByText(NOTICE)).toBeVisible();
  const form = page.getByRole("form", { name: "New campaign" });
  await form.getByLabel("Campaign name", { exact: true }).fill(NAME);
  await form.getByLabel("Published offer", { exact: true }).selectOption({ label: OFFER });
  await form.getByLabel("Mode", { exact: true }).selectOption("fixture");
  await form.getByLabel("investigate", { exact: true }).check();
  await form.getByRole("button", { name: "Create campaign" }).click();
  await expect(page.getByRole("heading", { level: 1, name: NAME })).toBeVisible();
  await expect(page.getByText(NOTICE)).toBeVisible();
  await expect(page.getByText(/test-only fixture campaign/)).toBeVisible();

  const candidates = page.getByRole("table", { name: "Candidates" });
  const school = candidates.getByRole("row").filter({ hasText: SCHOOL }).filter({ hasText: "qualifies" });
  await school.getByRole("button", { name: "Approve for drafting" }).click();
  await expect(page.getByRole("list", { name: "Campaign decisions" }).getByText(/approved for drafting/)).toBeVisible();
  const other = candidates.getByRole("row").filter({ hasText: "not assessed" }).first();
  await other.getByRole("button", { name: "Exclude" }).click();
  await expect(page.getByRole("list", { name: "Campaign decisions" }).getByText(/excluded/)).toBeVisible();
  await expect(page.getByRole("button", { name: /send|launch|whatsapp|message|enrol|draft now/i })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Activate internal planning" })).toHaveCount(0); // fixture: never active

  await page.getByRole("button", { name: "Pause campaign" }).click();
  await expect(page.getByRole("status").filter({ hasText: "Status: paused" })).toBeVisible();
  await expect(candidates.getByRole("button", { name: "Approve for drafting" })).toHaveCount(0);
});

test("CAMPAIGN-10 observer reads the campaign without controls", async ({ page }) => {
  await login(page, "observer");
  await openCampaign(page);
  await expect(page.getByText(NOTICE)).toBeVisible();
  await expect(page.getByRole("button")).toHaveCount(0);
});

test("CAMPAIGN-10 paused campaign and its decisions survive an api/web restart @after-restart", async ({ page }) => {
  await login(page, "operator");
  await openCampaign(page);
  await expect(page.getByRole("status").filter({ hasText: "Status: paused" })).toBeVisible();
  const decisions = page.getByRole("list", { name: "Campaign decisions" });
  await expect(decisions.getByText(/approved for drafting/)).toBeVisible();
  await expect(decisions.getByText(/excluded/)).toBeVisible();
});
