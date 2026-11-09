import { expect, test } from "@playwright/test";

import { login } from "./helpers";

// KNOW-10 (P6.2): a grounded draft beside a signed inbound message from a known synthetic contact (…888), with its
// citations, and an abstention for an opt-out. Drafts are never sent; no Meta host is ever reached.

test.describe.configure({ mode: "serial" });

const SCHOOL = "Contact at E2E Reply School (Synthetic)";

test("KNOW-10 operator gets a cited draft, rejects it, and an opt-out gets no draft", async ({ page }) => {
  const egress: string[] = [];
  await page.route(/graph\.facebook\.com|facebook\.com|whatsapp\.(com|net)/, (route) => {
    egress.push(route.request().url());
    return route.abort();
  });
  await login(page, "operator");
  await page.goto("/inbox/whatsapp");
  await page.getByRole("link", { name: SCHOOL }).click();
  const timeline = page.getByRole("list", { name: "Timeline" });
  await expect(timeline.getByRole("region", { name: "Intent for review" })).toHaveCount(2, { timeout: 30_000 });
  const asked = timeline.getByRole("listitem", { name: "Inbound message" }).filter({ hasText: "Do you support admissions" });
  const suggestion = asked.getByRole("region", { name: "Suggested reply" });
  await suggestion.getByRole("button", { name: "Suggest a reply" }).click();
  await expect(suggestion.getByText(/DRAFT — NOT SENT/)).toBeVisible();
  await expect(suggestion.locator("blockquote")).toContainText("Online admissions intake with a document checklist");
  await expect(suggestion.locator("blockquote")).toContainText("Fee vouchers and arrears tracking");
  const citations = suggestion.getByRole("list", { name: "Citations" });
  await expect(citations.getByRole("listitem")).toHaveCount(2);
  await expect(citations).toContainText("admissions_intake");
  await expect(suggestion).toContainText("rules only, no model · nothing here is sent");
  await expect(page.getByRole("button", { name: /\bsend\b|reply now|approve/i })).toHaveCount(0);
  await suggestion.getByLabel("Reason").fill("Wrong tone for this school");
  await suggestion.getByRole("button", { name: "Reject suggestion" }).click();
  await expect(suggestion).toContainText("rejected: Wrong tone for this school");

  const optOut = timeline.getByRole("listitem", { name: "Inbound message" }).filter({ hasText: "Please stop contacting us" });
  const none = optOut.getByRole("region", { name: "Suggested reply" });
  await none.getByRole("button", { name: "Suggest a reply" }).click();
  await expect(none.getByText("ABSTAINED")).toBeVisible();
  await expect(none).toContainText("No draft: opt out");
  await expect(none.locator("blockquote")).toHaveCount(0);
  expect(egress).toEqual([]);
});

test("KNOW-10 drafts and their rejection survive an api/web restart @after-restart", async ({ page }) => {
  await login(page, "operator");
  await page.goto("/inbox/whatsapp");
  await page.getByRole("link", { name: SCHOOL }).click();
  const asked = page.getByRole("listitem", { name: "Inbound message" }).filter({ hasText: "Do you support admissions" });
  await expect(asked.getByRole("region", { name: "Suggested reply" })).toContainText("rejected: Wrong tone for this school");
});
