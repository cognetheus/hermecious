import { expect, test } from "@playwright/test";

import { login } from "./helpers";

// INBOX-10 (P5.4): the read-only WhatsApp inbox over signed synthetic inbound messages seeded by scripts/test-e2e.sh
// through the real P5.2 receive path. No reply/send surface exists, markup in a message is inert text, and no
// request ever leaves for Meta.

test.describe.configure({ mode: "serial" });

const SENDER = "+92 ••••••• 777";

test("INBOX-10 operator reads a signed conversation, read-only, and marks it reviewed", async ({ page }) => {
  const egress: string[] = [];
  await page.route(/graph\.facebook\.com|facebook\.com|whatsapp\.(com|net)/, (route) => {
    egress.push(route.request().url());
    return route.abort();
  });
  page.on("dialog", () => {
    throw new Error("a script from a message executed");
  });
  await login(page, "operator");
  await page.getByRole("link", { name: "Inbox" }).click();
  await expect(page.getByRole("heading", { level: 1, name: "Inbox · WhatsApp" })).toBeVisible();
  await expect(page.getByRole("note")).toContainText("READ ONLY");
  const row = page.getByRole("list", { name: "Conversations" }).getByRole("listitem").filter({ hasText: SENDER });
  await expect(row).toContainText("TEST");
  await expect(row).toContainText("(Asia/Karachi)");
  // INBOX-07: the UTC instant is shown converted to Asia/Karachi, not merely labelled.
  const utc = await page.evaluate(async () => {
    const body = (await (await fetch("/api/v1/inbox/whatsapp/threads")).json()) as {
      items: { last_activity_at: string; party: { address: string } }[];
    };
    return body.items.find((t) => t.party.address.endsWith("777"))!.last_activity_at;
  });
  const karachi = new Intl.DateTimeFormat("en-GB", { timeZone: "Asia/Karachi", dateStyle: "medium", timeStyle: "short" }).format(new Date(utc));
  await expect(row).toContainText(karachi);
  // The worker processes the seeded signed items asynchronously; polling refreshes the list.
  await expect(row).toContainText("4 unread", { timeout: 30_000 });
  await row.getByRole("link", { name: "Unmatched WhatsApp contact" }).click();

  await expect(page.getByRole("heading", { level: 1, name: "Unmatched WhatsApp contact" })).toBeVisible();
  await expect(page.getByText("This sender is not linked to any school or contact.")).toBeVisible();
  const timeline = page.getByRole("list", { name: "Timeline" });
  await expect(timeline.getByText("Assalam o alaikum, fees module ke baare mein batayein")).toBeVisible();
  const urdu = timeline.getByText("کیا آپ ڈیمو دکھا سکتے ہیں؟");
  await expect(urdu).toHaveAttribute("dir", "auto");
  await expect(timeline.getByText("<img src=x onerror=alert(1)><script>alert(2)</script>")).toBeVisible();
  await expect(page.locator("main img, main script")).toHaveCount(0);
  await expect(timeline.getByText("Attachment or unsupported message (not downloaded)")).toBeVisible();
  // No message composition anywhere: the only inputs are the P6.1 intent-review and P6.3 ownership forms.
  await expect(page.locator("main textarea")).toHaveCount(0);
  await expect(page.locator("main input:not(form[aria-label='Review intent'] input, form[aria-label='Change ownership'] input)")).toHaveCount(0);
  // P6.1: each signed message carries an intent observation for human review (rules only), never an action.
  const intents = timeline.getByRole("region", { name: "Intent for review" });
  await expect(intents).toHaveCount(4, { timeout: 30_000 });
  await expect(intents.filter({ hasText: "Intent (for review): needs details" })).toHaveCount(1);
  await expect(intents.filter({ hasText: "Intent (for review): request demo" })).toHaveCount(1);
  await expect(intents.first()).toContainText("rules only, no model");
  await expect(intents.first()).toContainText("nothing happens automatically");
  // "Suggest a reply" only drafts (P6.2); there is still no way to send, approve, enrol or record consent.
  await expect(page.getByRole("button", { name: /\bsend\b|reply now|approve|enrol|consent/i })).toHaveCount(0);
  expect(await page.content()).not.toContain("920000000777"); // the raw number never reaches the browser

  const demo = intents.filter({ hasText: "Intent (for review): request demo" });
  await demo.getByLabel("Correct label").selectOption("interested");
  await demo.getByRole("button", { name: "Record review" }).click();
  await expect(timeline.getByText("Reviewed: corrected as interested")).toBeVisible();
  await page.getByRole("button", { name: "Mark reviewed" }).click();
  await expect(page.getByText("All messages reviewed.")).toBeVisible();
  expect(egress).toEqual([]);
});

test("INBOX-10 observer cannot open the inbox", async ({ page }) => {
  await login(page, "observer");
  await page.goto("/inbox/whatsapp");
  await expect(page.getByText("The inbox is available to owners and operators only.")).toBeVisible();
  await expect(page.getByRole("list", { name: "Conversations" })).toHaveCount(0);
});

test("INBOX-10 the timeline and review state survive an api/web restart @after-restart", async ({ page }) => {
  await login(page, "operator");
  await page.goto("/inbox/whatsapp");
  const row = page.getByRole("list", { name: "Conversations" }).getByRole("listitem").filter({ hasText: SENDER });
  await expect(row).toContainText("reviewed");
  await row.getByRole("link", { name: "Unmatched WhatsApp contact" }).click();
  await expect(page.getByRole("list", { name: "Timeline" }).getByRole("listitem")).toHaveCount(4);
  await expect(page.getByText("All messages reviewed.")).toBeVisible();
});
