import { expect, test } from "@playwright/test";

import { login } from "./helpers";

// EVAL-10: evidence review UI -> quality report -> linked correction -> truthful status. The e2e data is synthetic,
// so the run must end BLOCKED and the enrollment gate must stay CLOSED. Named to run after the other journeys.

test.describe.configure({ mode: "serial" });

test("EVAL-10 operator reviews displayed claims; a synthetic corpus can never open the gate", async ({ page }) => {
  await login(page, "operator");
  await page.getByRole("link", { name: "Evidence quality" }).click();
  await expect(page.getByRole("status").filter({ hasText: "Enrollment quality gate: CLOSED" })).toBeVisible();
  const form = page.getByRole("form", { name: "Start evaluation" });
  await form.getByLabel("Selection seed", { exact: true }).fill("e2e-seed");
  await form.getByLabel(/Include synthetic accounts/).check();
  await form.getByRole("button", { name: "Start evaluation" }).click();
  await expect(page.getByRole("heading", { level: 1, name: "Evidence evaluation (baseline)" })).toBeVisible();
  await expect(page.getByText(/Corpus SYNTHETIC_CORPUS/)).toBeVisible();
  // A synthetic corpus is BLOCKED from the start: it can be reviewed, but it can never pass.
  await expect(page.getByRole("status").filter({ hasText: "State: BLOCKED" })).toBeVisible();

  const claims = page.getByRole("article");
  const total = await claims.count();
  expect(total).toBeGreaterThan(0);
  for (let i = 0; i < total; i++) {
    const claim = claims.nth(i);
    const text = (await claim.textContent()) ?? "";
    const verdict = text.includes("public_contact_channel") ? "unsupported" : "supported";
    await claim.getByLabel("Verdict", { exact: true }).selectOption(verdict);
    await claim.getByRole("button", { name: "Save verdict" }).click();
    const status = claim.getByRole("status");
    await expect(status).not.toHaveText("");
    if (!(await status.textContent())?.includes("Saved")) {
      // The server refuses "supported" for evidence that is not currently usable: record it honestly instead.
      await claim.getByLabel("Verdict", { exact: true }).selectOption("unverifiable");
      await claim.getByRole("button", { name: "Save verdict" }).click();
      await expect(status).toHaveText("Saved");
    }
  }
  await page.reload();
  await page.getByRole("button", { name: "Finalize evaluation" }).click();
  await expect(page.getByRole("status").filter({ hasText: /State: BLOCKED — corpus is synthetic_corpus/ })).toBeVisible();
  await expect(page.getByText(/Supported \d+\/\d+; failed claims still displayed: [1-9]/)).toBeVisible();

  const failed = claims.filter({ hasText: "public_contact_channel" }).filter({ hasText: "verdict: unsupported" }).first();
  await failed.getByRole("button", { name: "Withdraw as fact (record correction)" }).click();
  await expect(failed.getByText(/withdrawn as fact \(correction recorded\)/)).toBeVisible();
  await page.getByRole("link", { name: "All evaluations" }).click();
  await expect(page.getByRole("status").filter({ hasText: "Enrollment quality gate: CLOSED" })).toBeVisible();
});

test("EVAL-10 observer reads the evaluation without review controls", async ({ page }) => {
  await login(page, "observer");
  await page.goto("/quality");
  await expect(page.getByRole("form", { name: "Start evaluation" })).toHaveCount(0);
  await page.getByRole("table", { name: "Evaluations, newest first" }).getByRole("link").first().click();
  await expect(page.getByRole("status").filter({ hasText: "State: BLOCKED" })).toBeVisible();
  await expect(page.getByRole("button")).toHaveCount(0);
});

test("EVAL-10 evaluation and correction survive an api/web restart @after-restart", async ({ page }) => {
  await login(page, "operator");
  await page.goto("/quality");
  await page.getByRole("table", { name: "Evaluations, newest first" }).getByRole("link").first().click();
  await expect(page.getByRole("status").filter({ hasText: "State: BLOCKED" })).toBeVisible();
  await expect(page.getByText(/withdrawn as fact \(correction recorded\)/)).toBeVisible();
});
