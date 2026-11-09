import { expect, test } from "@playwright/test";

import { login } from "./helpers";

// OWNER-09 (P6.3): an operator takes over a conversation with a reason, sees the owner/state/generation, the
// handoff queue, a stale screen fails loudly instead of overwriting, and the conversation is resolved. Auto replies
// are shown as disabled throughout; nothing can be sent and no Meta host is ever reached.

test.describe.configure({ mode: "serial" });

const SCHOOL = "Contact at E2E Reply School (Synthetic)";

test("OWNER-09 takeover, handoff queue, stale-revision conflict and resolve", async ({ page }) => {
  const egress: string[] = [];
  await page.route(/graph\.facebook\.com|facebook\.com|whatsapp\.(com|net)/, (route) => {
    egress.push(route.request().url());
    return route.abort();
  });
  await login(page, "operator");
  await page.goto("/inbox/whatsapp");
  await page.getByRole("link", { name: SCHOOL }).click();
  await page.waitForURL(/\/inbox\/whatsapp\/[0-9a-f-]{36}$/);
  const threadUrl = page.url();
  const panel = page.getByRole("region", { name: "Ownership" });
  await expect(panel).toContainText("AUTO REPLIES DISABLED");
  await expect(panel).toContainText("Owner: nobody yet · state new · generation 0");
  const form = panel.getByRole("form", { name: "Change ownership" });
  await form.getByLabel("Action").selectOption("takeover");
  await form.getByLabel("Reason").selectOption("operator_takeover");
  await form.getByRole("button", { name: "Apply" }).click();
  await expect(panel).toContainText("Owner: E2E operator · state human owned · generation 1");
  await expect(panel.getByLabel("Handoff task")).toContainText("operator takeover");
  await expect(form.getByLabel("Action").locator("option", { hasText: "block" })).toHaveCount(0); // owner-only
  await expect(page.getByRole("button", { name: /\bsend\b|reply now|approve|auto/i })).toHaveCount(0);

  await page.getByRole("link", { name: "Back to inbox" }).click();
  await page.getByRole("link", { name: "Handoff queue" }).click();
  const queue = page.getByRole("list", { name: "Handoff tasks" });
  await expect(queue.getByRole("listitem")).toHaveCount(1);
  await expect(queue).toContainText("operator takeover · open · assigned to E2E operator");
  await expect(page.getByRole("note")).toContainText("AUTO REPLIES DISABLED");

  // Two screens on the same conversation: the second one is stale after the first acts.
  const other = await page.context().newPage();
  await other.goto(threadUrl);
  await page.goto(threadUrl);
  await form.getByLabel("Action").selectOption("pause");
  await form.getByLabel("Reason").selectOption("quality_concern");
  await form.getByRole("button", { name: "Apply" }).click();
  await expect(panel).toContainText("state paused · generation 2");
  const staleForm = other.getByRole("region", { name: "Ownership" }).getByRole("form", { name: "Change ownership" });
  await staleForm.getByLabel("Action").selectOption("resolve");
  await staleForm.getByRole("button", { name: "Apply" }).click();
  await expect(staleForm.getByRole("status")).toContainText("reload");
  await other.close();

  await page.reload();
  await form.getByLabel("Action").selectOption("resolve");
  await form.getByLabel("Reason").selectOption("resolved_by_operator");
  await form.getByRole("button", { name: "Apply" }).click();
  await expect(panel).toContainText("state resolved · generation 3");
  await panel.getByText("Ownership history (3)").click();
  await expect(panel.getByRole("list", { name: "Ownership history" }).getByRole("listitem")).toHaveCount(3);
  await page.goto("/inbox/whatsapp/handoffs");
  await expect(page.getByText("No conversation is waiting for a person.")).toBeVisible();
  expect(egress).toEqual([]);
});

test("OWNER-09 ownership survives an api/web restart @after-restart", async ({ page }) => {
  await login(page, "operator");
  await page.goto("/inbox/whatsapp");
  await page.getByRole("link", { name: SCHOOL }).click();
  await expect(page.getByRole("region", { name: "Ownership" })).toContainText("state resolved · generation 3");
});
