import { expect, type Page, test } from "@playwright/test";

import { login, RUN } from "./helpers";

// DRAFT-10: synthetic fixture campaign -> approved candidate -> grounded draft -> evidence drilldown -> regenerate
// -> pause makes it stale -> restart. Runs after wrap-campaigns.spec.ts. Nothing is approved for sending or sent.

test.describe.configure({ mode: "serial" });

const SCHOOL = "Crescent Valley Grammar School (Synthetic)";
const OFFER = `school_core_${RUN.toLowerCase().replace(/[^a-z0-9_]/g, "")}`;
const NAME = `Draft pilot ${RUN}`;
const NOTICE = "DRAFT ONLY — NOT APPROVED FOR SENDING";

async function openStudio(page: Page) {
  await page.goto("/campaigns");
  await page.getByRole("list", { name: "Campaigns" }).getByRole("link", { name: NAME }).click();
  await page.getByRole("list", { name: "Campaign decisions" }).getByRole("link", { name: "Draft Studio" }).click();
  await expect(page.getByRole("heading", { level: 1, name: "Draft Studio" })).toBeVisible();
}

test("DRAFT-10 operator generates a grounded, never-sendable draft and inspects its evidence", async ({ page }) => {
  await login(page, "operator");
  await page.goto("/campaigns");
  const form = page.getByRole("form", { name: "New campaign" });
  await form.getByLabel("Campaign name", { exact: true }).fill(NAME);
  await form.getByLabel("Published offer", { exact: true }).selectOption({ label: OFFER });
  await form.getByLabel("Mode", { exact: true }).selectOption("fixture");
  await form.getByLabel("investigate", { exact: true }).check();
  await form.getByRole("button", { name: "Create campaign" }).click();
  await expect(page.getByRole("heading", { level: 1, name: NAME })).toBeVisible();
  const row = page.getByRole("table", { name: "Candidates" }).getByRole("row").filter({ hasText: SCHOOL }).filter({ hasText: "qualifies" });
  await row.getByRole("button", { name: "Approve for drafting" }).click();
  await page.getByRole("list", { name: "Campaign decisions" }).getByRole("link", { name: "Draft Studio" }).click();

  await expect(page.getByText(NOTICE)).toBeVisible();
  await expect(page.getByRole("option", { name: "Urdu (no reviewed template yet)" })).toBeDisabled();
  await page.getByRole("button", { name: "Generate draft" }).click();
  const latest = page.getByRole("article", { name: "Latest draft" });
  await expect(latest.getByRole("heading", { name: /Revision 1 \(school_introduction_v1, en-PK\) — needs review/ })).toBeVisible();
  await expect(latest.getByText(/This is the CoderzHunt team in Lahore\..*reply STOP/s).first()).toBeVisible();
  const evidence = latest.getByRole("table", { name: "Evidence behind each sentence" });
  await expect(evidence.getByText(/offer claim (admissions_intake|fee_tracking) \(caps-e2e\)/)).toBeVisible();
  await expect(evidence.getByText(/discovery question for/)).toBeVisible();
  await expect(evidence.getByText(/^fact /).first()).toBeVisible();
  await expect(latest.getByText(/Excel|manual|guarantee|PKR|https?:\/\/\S+\s*$/)).toHaveCount(0);
  await expect(page.getByRole("button", { name: /send|approve for sending|queue|schedule|whatsapp|connect/i })).toHaveCount(0);

  await page.getByLabel("Reason to regenerate", { exact: true }).fill("Prefer the question template");
  await page.getByRole("button", { name: "Regenerate (new revision)" }).click();
  await expect(latest.getByRole("heading", { name: /Revision 2/ })).toBeVisible();
  await expect(page.getByRole("region", { name: "Earlier revisions" }).getByText(/Revision 1/)).toBeVisible();

  await page.getByRole("link", { name: "Back to campaign" }).click();
  await page.getByRole("button", { name: "Pause campaign" }).click();
  await expect(page.getByRole("status").filter({ hasText: "Status: paused" })).toBeVisible();
  await page.getByRole("list", { name: "Campaign decisions" }).getByRole("link", { name: "Draft Studio" }).click();
  await expect(page.getByRole("heading", { name: /Revision 2 .* BLOCKED: stale/ })).toBeVisible();
  await expect(page.getByText(/Stale because: campaign_paused/)).toBeVisible();
});

test("DRAFT-10 observer reads drafts without controls", async ({ page }) => {
  await login(page, "observer");
  await openStudio(page);
  await expect(page.getByText(NOTICE)).toBeVisible();
  await expect(page.getByRole("button")).toHaveCount(0);
});

test("DRAFT-10 drafts and history survive an api/web restart @after-restart", async ({ page }) => {
  await login(page, "operator");
  await openStudio(page);
  await expect(page.getByRole("heading", { name: /Revision 2 .* BLOCKED: stale/ })).toBeVisible();
  await expect(page.getByRole("region", { name: "Earlier revisions" }).getByText(/Revision 1/)).toBeVisible();
});
