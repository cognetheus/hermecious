import { expect, type Page, test } from "@playwright/test";

import { login, RUN } from "./helpers";

// APPROVAL-10 (P4.4): generate -> refused injected edit -> grounded edit (new revision) -> eligibility-gated
// "Approve content only" (simulation only) -> pause stales it -> restart. Runs after wrap-eligibility.spec.ts,
// whose contact (+92 ••••••• 101) is suppressed. Nothing is queued or sent.

test.describe.configure({ mode: "serial" });

const SCHOOL = "Crescent Valley Grammar School (Synthetic)";
const OFFER = `school_core_${RUN.toLowerCase().replace(/[^a-z0-9_]/g, "")}`;
const NAME = `Approval pilot ${RUN}`;
const FRESH = "+92 ••••••• 102";
const SUPPRESSED = "+92 ••••••• 101";

async function openStudio(page: Page) {
  await page.goto("/campaigns");
  await page.getByRole("list", { name: "Campaigns" }).getByRole("link", { name: NAME }).click();
  await page.getByRole("list", { name: "Campaign decisions" }).getByRole("link", { name: "Draft Studio" }).click();
  await expect(page.getByRole("heading", { level: 1, name: "Draft Studio" })).toBeVisible();
}

function karachiYesterday(): string {
  return new Date(Date.now() - 86_400_000 + 5 * 3_600_000).toISOString().slice(0, 16);
}

test("APPROVAL-10 edit, eligibility-gated content approval and invalidation; simulation only", async ({ page, browser }) => {
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
  await openStudio(page);
  await page.getByRole("button", { name: "Generate draft" }).click();
  const latest = page.getByRole("article", { name: "Latest draft" });
  await expect(latest.getByRole("heading", { name: /Revision 1 .* needs review/ })).toBeVisible();

  // A second synthetic contact with owner-verified opt-in.
  await page.getByRole("link", { name: "Account", exact: true }).click();
  await page.getByRole("link", { name: "Contacts and channel eligibility" }).click();
  const add = page.getByRole("form", { name: "Add contact" });
  await add.getByLabel("WhatsApp number", { exact: true }).fill("+92 000 0000102");
  await add.getByRole("button", { name: "Add contact" }).click();
  const contact = page.getByRole("article", { name: `Contact ${FRESH}` });
  const evidence = contact.getByRole("form", { name: "Record opt-in evidence" });
  await evidence.getByLabel("Proof reference", { exact: true }).fill("FORM-SYN-E2E-0002");
  await evidence.getByLabel("Opt-in given at (Asia/Karachi)", { exact: true }).fill(karachiYesterday());
  await evidence.getByRole("button", { name: "Record evidence" }).click();
  await expect(contact.getByRole("cell", { name: "pending (v1)" })).toBeVisible();
  const ownerPage = await browser.newPage();
  await login(ownerPage, "owner");
  await ownerPage.goto(page.url());
  const ownerContact = ownerPage.getByRole("article", { name: `Contact ${FRESH}` });
  await ownerContact.getByLabel("Reason (marketing)", { exact: true }).fill("Signed synthetic form checked");
  await ownerContact.getByRole("button", { name: "Verify evidence" }).click();
  await expect(ownerContact.getByRole("cell", { name: "verified (v2)" })).toBeVisible();
  await ownerPage.close();

  await openStudio(page);
  const body = (await latest.locator("pre").textContent()) ?? "";
  const editor = latest.getByRole("form", { name: "Edit draft" });
  await editor.getByLabel("Edited text", { exact: true }).fill(`${body} <script>alert(1)</script>`);
  await editor.getByLabel("Reason for edit", { exact: true }).fill("Try new wording");
  await editor.getByRole("button", { name: "Save as new revision" }).click();
  await expect(editor.getByRole("status")).toContainText("UNGROUNDED_TEXT");
  await editor.getByLabel("Edited text", { exact: true }).fill(body.replace(/We noticed that [^.]*\. /, ""));
  await editor.getByLabel("Reason for edit", { exact: true }).fill("Shorter, no observation");
  await editor.getByRole("button", { name: "Save as new revision" }).click();
  await expect(latest.getByRole("heading", { name: /Revision 2 .* needs review/ })).toBeVisible();
  await expect(latest.getByText(/edited by a person/)).toBeVisible();

  const approval = latest.getByRole("region", { name: "Content approval" });
  await expect(approval.getByText("Simulation only", { exact: true })).toBeVisible();
  await expect(approval.getByRole("status").first()).toHaveText("Not reviewed");
  const review = approval.getByRole("form", { name: "Review content" });
  await review.getByLabel("Review reason", { exact: true }).fill("Grounded and polite");
  await review.getByRole("button", { name: "Approve content only" }).click();
  await expect(review.getByRole("status")).toContainText("NO_CONTACT_SELECTED");
  await review.getByLabel("Contact", { exact: true }).selectOption({ label: `${SUPPRESSED} (suppressed)` });
  await review.getByLabel("Template", { exact: true }).selectOption("fx_tpl_marketing_intro_v1");
  await review.getByRole("button", { name: "Approve content only" }).click();
  await expect(review.getByRole("status")).toContainText("suppressed");
  await review.getByLabel("Contact", { exact: true }).selectOption({ label: FRESH });
  await review.getByRole("button", { name: "Approve content only" }).click();
  await expect(approval.getByText(/^Content approved \(simulation only\) — not queued, not sent, not a WhatsApp template approval$/)).toBeVisible();
  await expect(approval.getByText(new RegExp(`approved content by .* Grounded and polite · contact \\${FRESH.slice(0, 3)}`))).toBeVisible();
  await expect(page.getByRole("button", { name: /send|queue|schedule|whatsapp|dispatch/i })).toHaveCount(0);

  await page.getByRole("link", { name: "Back to campaign" }).click();
  await page.getByRole("button", { name: "Pause campaign" }).click();
  await expect(page.getByRole("status").filter({ hasText: "Status: paused" })).toBeVisible();
  await page.getByRole("list", { name: "Campaign decisions" }).getByRole("link", { name: "Draft Studio" }).click();
  await expect(approval.getByText(/Approval stale — no longer valid: .*campaign_paused/)).toBeVisible();
});

test("APPROVAL-10 observer reads approval status without controls", async ({ page }) => {
  await login(page, "observer");
  await openStudio(page);
  await expect(page.getByRole("region", { name: "Content approval" }).getByText(/Approval stale/)).toBeVisible();
  await expect(page.getByRole("button")).toHaveCount(0);
});

test("APPROVAL-10 review history survives an api/web restart and nothing restores the approval @after-restart", async ({ page }) => {
  await login(page, "operator");
  await openStudio(page);
  const approval = page.getByRole("region", { name: "Content approval" });
  await expect(approval.getByText(/Approval stale — no longer valid: .*campaign_paused/)).toBeVisible();
  await expect(approval.getByRole("list", { name: "Review history" }).getByText(/approved content \(revision 2\)/)).toBeVisible();
});
