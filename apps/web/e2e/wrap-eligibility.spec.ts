import { expect, type Page, test } from "@playwright/test";

import { login, RUN } from "./helpers";

// ELIG (P4.3): synthetic contact -> denied without opt-in -> pending evidence -> owner verifies -> simulation-only
// reading -> suppression wins -> restart. Runs after wrap-drafts.spec.ts. Nothing is queued or sent.

test.describe.configure({ mode: "serial" });

const SCHOOL = "Crescent Valley Grammar School (Synthetic)";
const OFFER = `school_core_${RUN.toLowerCase().replace(/[^a-z0-9_]/g, "")}`;
const NAME = `Eligibility pilot ${RUN}`;
const NOTICE = "Simulation eligibility only — sending disabled";
const MASKED = "+92 ••••••• 101";

async function openContacts(page: Page) {
  await page.goto("/campaigns");
  await page.getByRole("list", { name: "Campaigns" }).getByRole("link", { name: NAME }).click();
  await page.getByRole("list", { name: "Campaign decisions" }).getByRole("link", { name: "Draft Studio" }).click();
  await page.getByRole("link", { name: "Account", exact: true }).click();
  await page.getByRole("link", { name: "Contacts and channel eligibility" }).click();
  await expect(page.getByRole("heading", { level: 1, name: "Contacts and channel eligibility" })).toBeVisible();
}

async function check(page: Page, template = true) {
  const panel = page.getByRole("article", { name: `Contact ${MASKED}` }).getByRole("region", { name: "Eligibility check" });
  await panel.getByLabel("Purpose", { exact: true }).selectOption("marketing");
  await panel.getByLabel("Campaign", { exact: true }).selectOption({ label: NAME });
  await panel.getByLabel("Template", { exact: true }).selectOption(template ? "fx_tpl_marketing_intro_v1" : "");
  await panel.getByRole("button", { name: "Check eligibility" }).click();
  return panel.getByRole("region", { name: "Eligibility result" });
}

function karachiYesterday(): string {
  return new Date(Date.now() - 86_400_000 + 5 * 3_600_000).toISOString().slice(0, 16);
}

test("ELIG operator records evidence, owner verifies, suppression wins; simulation only", async ({ page, browser }) => {
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
  await expect(page.getByRole("list", { name: "Campaign decisions" }).getByText(/approved for drafting/)).toBeVisible();
  await openContacts(page);
  await expect(page.getByText(NOTICE)).toBeVisible();

  const add = page.getByRole("form", { name: "Add contact" });
  await add.getByLabel("WhatsApp number", { exact: true }).fill("+92 000 0000101");
  await add.getByLabel("Role", { exact: true }).selectOption("admissions_office");
  await add.getByRole("button", { name: "Add contact" }).click();
  const contact = page.getByRole("article", { name: `Contact ${MASKED}` });
  await expect(contact).toBeVisible();
  await expect(page.getByText("0000101")).toHaveCount(0); // never shown unmasked

  const denied = await check(page);
  await expect(denied.getByText("Decision: deny")).toBeVisible();
  await expect(denied.getByText(/no_opt_in_permission: No opt-in is on record\. A public phone number is not permission\./)).toBeVisible();

  const evidence = contact.getByRole("form", { name: "Record opt-in evidence" });
  await evidence.getByLabel("Proof reference", { exact: true }).fill("FORM-SYN-E2E-0001");
  await evidence.getByLabel("Opt-in given at (Asia/Karachi)", { exact: true }).fill(karachiYesterday());
  await evidence.getByRole("button", { name: "Record evidence" }).click();
  await expect(contact.getByRole("cell", { name: "pending (v1)" })).toBeVisible();
  await expect(contact.getByRole("button", { name: "Verify evidence" })).toHaveCount(0); // operators cannot verify
  const pendingResult = await check(page);
  await expect(pendingResult.getByText(/permission_unverified/)).toBeVisible();

  const ownerPage = await browser.newPage();
  await login(ownerPage, "owner");
  await openContacts(ownerPage);
  const ownerContact = ownerPage.getByRole("article", { name: `Contact ${MASKED}` });
  await ownerContact.getByLabel("Reason (marketing)", { exact: true }).fill("Signed synthetic form checked");
  await ownerContact.getByRole("button", { name: "Verify evidence" }).click();
  await expect(ownerContact.getByRole("cell", { name: "verified (v2)" })).toBeVisible();
  await expect(ownerContact.getByText(/verified by .* Signed synthetic form checked/)).toBeVisible();
  await ownerPage.close();

  await page.reload();
  const allowed = await check(page);
  // Business hours depend on the wall clock: inside them this is allow-for-simulation, outside them a deferral.
  await expect(allowed.getByText(/Decision: (allow for simulation|defer)/)).toBeVisible();
  await expect(allowed.getByText(/live send authorized: no/)).toBeVisible();
  const noTemplate = await check(page, false);
  await expect(noTemplate.getByText(/template_missing/)).toBeVisible();

  await contact.getByRole("button", { name: "Suppress number" }).click();
  await expect(contact.getByText(/Suppressed \(opt out\) since .* overrides every campaign/)).toBeVisible();
  const suppressed = await check(page);
  await expect(suppressed.getByText("Decision: deny")).toBeVisible();
  await expect(suppressed.getByText(/suppressed: This number opted out/)).toBeVisible();
  await expect(page.getByRole("button", { name: /send|queue|schedule|whatsapp|approve/i })).toHaveCount(0);
});

test("ELIG observer reads masked status without controls", async ({ page }) => {
  await login(page, "observer");
  await openContacts(page);
  await expect(page.getByText(NOTICE)).toBeVisible();
  const contact = page.getByRole("article", { name: `Contact ${MASKED}` });
  await expect(contact.getByRole("cell", { name: "verified (v2)" })).toBeVisible();
  await expect(contact.getByRole("cell", { name: "restricted" }).first()).toBeVisible();
  await expect(page.getByRole("button")).toHaveCount(0);
});

test("ELIG evidence and suppression survive an api/web restart @after-restart", async ({ page }) => {
  await login(page, "operator");
  await openContacts(page);
  const contact = page.getByRole("article", { name: `Contact ${MASKED}` });
  await expect(contact.getByText(/Suppressed \(opt out\)/)).toBeVisible();
  await expect(contact.getByRole("cell", { name: "verified (v2)" })).toBeVisible();
  const result = await check(page);
  await expect(result.getByText("Decision: deny")).toBeVisible();
});
