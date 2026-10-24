import { expect, type Page, test } from "@playwright/test";

import { login, RUN } from "./helpers";

// SIM-10 (P4.5): approved content for a verified synthetic contact -> Dry Run -> per-account report with
// denominators -> cancel -> observer -> restart. Runs after wrap-review.spec.ts, whose contact +92 ••••••• 102 is
// verified. Zero egress: the simulator has no real transport.

test.describe.configure({ mode: "serial" });

const SCHOOL = "Crescent Valley Grammar School (Synthetic)";
const OFFER = `school_core_${RUN.toLowerCase().replace(/[^a-z0-9_]/g, "")}`;
const NAME = `Dry run pilot ${RUN}`;
const LABEL = "SIMULATION ONLY — 0 real messages sent";

async function openCampaign(page: Page) {
  await page.goto("/campaigns");
  await page.getByRole("list", { name: "Campaigns" }).getByRole("link", { name: NAME }).click();
  await expect(page.getByRole("heading", { level: 1, name: NAME })).toBeVisible();
}

test("SIM-10 operator dry-runs a fixture campaign and reads an exact, reconciled report", async ({ page }) => {
  await login(page, "operator");
  await page.goto("/campaigns");
  const form = page.getByRole("form", { name: "New campaign" });
  await form.getByLabel("Campaign name", { exact: true }).fill(NAME);
  await form.getByLabel("Published offer", { exact: true }).selectOption({ label: OFFER });
  await form.getByLabel("Mode", { exact: true }).selectOption("fixture");
  await form.getByLabel("investigate", { exact: true }).check();
  await form.getByRole("button", { name: "Create campaign" }).click();
  const row = page.getByRole("table", { name: "Candidates" }).getByRole("row").filter({ hasText: SCHOOL }).filter({ hasText: "qualifies" });
  await row.getByRole("button", { name: "Approve for drafting" }).click();
  await expect(page.getByRole("list", { name: "Campaign decisions" }).getByText(/approved for drafting/)).toBeVisible();
  await page.getByRole("list", { name: "Campaign decisions" }).getByRole("link", { name: "Draft Studio" }).click();
  await page.getByRole("button", { name: "Generate draft" }).click();
  const approval = page.getByRole("article", { name: "Latest draft" }).getByRole("region", { name: "Content approval" });
  const review = approval.getByRole("form", { name: "Review content" });
  await review.getByLabel("Contact", { exact: true }).selectOption({ label: "+92 ••••••• 102" });
  await review.getByLabel("Template", { exact: true }).selectOption("fx_tpl_marketing_intro_v1");
  await review.getByLabel("Review reason", { exact: true }).fill("Grounded and polite");
  await review.getByRole("button", { name: "Approve content only" }).click();
  await expect(approval.getByText(/^Content approved \(simulation only\)/)).toBeVisible();

  await openCampaign(page);
  await expect(page.getByText(LABEL, { exact: false }).first()).toBeVisible();
  await page.getByLabel("Scenario", { exact: true }).selectOption("all_allow");
  await page.getByRole("button", { name: "Dry Run" }).click();
  await expect(page.getByRole("heading", { level: 1, name: "Dry run report" })).toBeVisible();
  await expect(page.getByRole("alert").filter({ hasText: LABEL })).toBeVisible();
  await expect(page.getByRole("status").filter({ hasText: "Status: completed" })).toBeVisible({ timeout: 30_000 });
  const school = page.getByRole("table", { name: "Per-account decisions" }).getByRole("row").filter({ hasText: SCHOOL });
  // Business hours follow the wall clock: inside them the item is accepted (simulated delivery), outside deferred.
  await expect(school.getByRole("cell", { name: /^(accepted|deferred)$/ })).toBeVisible();
  await expect(school.getByText(/sim delivered \(sim-[0-9a-f]{24}\)|not attempted/)).toBeVisible();
  const decisions = page.getByRole("list", { name: "Decisions" });
  await expect(decisions.getByText(/^Accepted for simulation: \d+ of \d+/)).toBeVisible();
  await expect(decisions.getByText(/^Invalid: \d+ of \d+/)).toBeVisible();
  await expect(page.getByText(/Counts reconcile with the records considered/)).toBeVisible();
  await expect(page.getByRole("list", { name: "Missing prerequisites" }).getByText(/official WhatsApp template approval/)).toBeVisible();
  await expect(page.getByRole("link", { name: "Download redacted CSV" })).toBeVisible();
  await expect(page.getByRole("button", { name: /send|queue|schedule|whatsapp|dispatch|provider/i })).toHaveCount(0);

  // A second run: cancel it if it is still active; either way it ends in a terminal, labelled state.
  await page.getByRole("link", { name: "Back to campaign" }).click();
  await page.getByLabel("Scenario", { exact: true }).selectOption("provider_429_mock");
  await page.getByRole("button", { name: "Dry Run" }).click();
  await expect(page.getByRole("heading", { level: 1, name: "Dry run report" })).toBeVisible();
  const cancel = page.getByRole("button", { name: "Cancel run" });
  if (await cancel.isVisible()) await cancel.click().catch(() => undefined);
  await expect(page.getByRole("status").filter({ hasText: /Status: (cancelled|completed)/ })).toBeVisible({ timeout: 30_000 });
});

test("SIM-10 observer reads dry-run reports without controls", async ({ page }) => {
  await login(page, "observer");
  await openCampaign(page);
  await expect(page.getByRole("button")).toHaveCount(0);
  await page.getByRole("list", { name: "Dry runs" }).getByRole("link", { name: /all allow — completed/ }).click();
  await expect(page.getByRole("alert").filter({ hasText: LABEL })).toBeVisible();
  await expect(page.getByRole("button")).toHaveCount(0);
});

test("SIM-10 dry-run reports survive an api/web restart @after-restart", async ({ page }) => {
  await login(page, "operator");
  await openCampaign(page);
  await page.getByRole("list", { name: "Dry runs" }).getByRole("link", { name: /all allow — completed/ }).click();
  await expect(page.getByRole("status").filter({ hasText: "Status: completed" })).toBeVisible();
  await expect(page.getByText(/report digest [0-9a-f]{12}/)).toBeVisible();
  await expect(page.getByRole("table", { name: "Per-account decisions" }).getByRole("row").filter({ hasText: SCHOOL })).toBeVisible();
});
