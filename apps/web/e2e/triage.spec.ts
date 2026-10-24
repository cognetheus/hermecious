import { expect, type Page, test } from "@playwright/test";

import { login, RUN } from "./helpers";

// QUALIFY-10: account -> accepted research facts -> school brief -> four-axis assessment against a published offer
// -> reviewer override -> restart. Named so it runs after research.spec.ts and school.spec.ts (alphabetical order).

test.describe.configure({ mode: "serial" });

const SCHOOL = "Crescent Valley Grammar School (Synthetic)";
const CONTACT_NOW = "Research priority: contact candidate — channel eligibility not checked.";
const OFFER = `school_core_${RUN.toLowerCase().replace(/[^a-z0-9_]/g, "")}`;

// eslint-disable-next-line @typescript-eslint/no-explicit-any -- untyped JSON from the API under test
async function call(page: Page, method: string, path: string, body?: unknown): Promise<{ status: number; data: any }> {
  return page.evaluate(
    async ({ method, path, body }) => {
      const csrf = (await (await fetch("/api/v1/auth/csrf")).json()).csrf_token as string;
      const response = await fetch(path, {
        method,
        headers: { "Content-Type": "application/json", "X-CSRF-Token": csrf },
        body: body === undefined ? undefined : JSON.stringify(body),
      });
      return { status: response.status, data: await response.json() };
    },
    { method, path, body },
  );
}

async function openAccount(page: Page) {
  await page.goto("/discovery");
  await page.getByRole("table", { name: "Discovery runs, newest first" }).getByRole("link").first().click();
  const card = page.getByRole("article", { name: `Listing ${SCHOOL}` }).filter({ hasText: "Johar Town" });
  await card.getByRole("link", { name: "open account" }).click();
  await expect(page.getByRole("heading", { level: 1, name: SCHOOL })).toBeVisible();
  return page.locator("section").filter({ has: page.getByRole("heading", { name: "Qualification" }) });
}

test("QUALIFY-10 owner publishes an evidenced offer (P1.3)", async ({ page }) => {
  await login(page, "owner");
  const created = await call(page, "POST", "/api/v1/offers", { code: OFFER, audience: "Independent schools in Lahore" });
  expect(created.status).toBe(201);
  const evidence = { ref: "internal-demo:admissions-e2e", type: "internal-demo", recorded_at: "2026-10-01T00:00:00+00:00", description: "Internal demo" };
  const claim = (code: string) => ({
    capability_code: code, summary: `${code} module`, readiness: "available", approved_for_sales: true,
    evidence_refs: [evidence.ref], approval_note: "Owner reviewed the internal demo",
  });
  const revision = await call(page, "POST", `/api/v1/offers/${created.data.id}/revisions`, {
    expected_version: created.data.version,
    content: { capability_version: "caps-e2e", capability_matrix: [claim("admissions_intake"), claim("fee_tracking")], evidence_references: [evidence] },
  });
  expect(revision.status).toBe(201);
  const offer = await call(page, "GET", `/api/v1/offers/${created.data.id}`);
  const published = await call(page, "POST", `/api/v1/offers/${created.data.id}/publish`, { revision: 1, expected_version: offer.data.offer?.version ?? offer.data.version });
  expect(published.status).toBe(200);
});

test("QUALIFY-10 operator assesses with cited evidence, sees a research priority only, then overrides", async ({ page }) => {
  await login(page, "operator");
  const panel = await openAccount(page);
  const accountId = page.url().split("/accounts/")[1];
  // Accept the remaining proposed research claims (the UI path for one claim is covered by RESEARCH-10).
  const runs = await call(page, "GET", `/api/v1/accounts/${accountId}/research-runs`);
  const detail = await call(page, "GET", `/api/v1/research-runs/${runs.data.items[0].id}`);
  for (const claim of detail.data.claims) {
    const wanted = claim.status === "proposed" && (claim.value.area === "fees" || claim.value.channel === "website_form" || claim.value.signal === "admissions process announced");
    if (wanted) {
      const reviewed = await call(page, "POST", `/api/v1/research-claims/${claim.id}/review`, {
        action: "accept", expected_version: claim.version, reason: "Checked the cited sentence", idempotency_key: `e2e-${claim.id}`,
      });
      expect(reviewed.status).toBe(200);
    }
  }
  await page.reload();

  await panel.getByLabel("Published offer", { exact: true }).selectOption({ label: OFFER });
  await panel.getByRole("button", { name: "Assess account" }).click();
  await expect(panel.getByRole("status").filter({ hasText: CONTACT_NOW })).toBeVisible();
  for (const label of ["Customer fit: strong", "Need evidence: moderate", "Accessibility: moderate", "Delivery fit: strong"]) {
    await expect(panel.getByRole("heading", { name: label })).toBeVisible();
  }
  await expect(panel.getByText(/channel eligibility: not checked/)).toBeVisible();
  await expect(panel.getByText(/not permission to send marketing/).first()).toBeVisible();
  await expect(page.getByRole("button", { name: /send|enrol|enroll|message|campaign/i })).toHaveCount(0);
  await expect(panel.getByText(/\d+\s*%/)).toHaveCount(0);
  await expect(panel.getByText(/probability/i)).toHaveCount(1); // only the "no score or probability" disclaimer

  const form = panel.getByRole("form", { name: "Override assessment" });
  await form.getByLabel("Decision", { exact: true }).selectOption("investigate");
  await form.getByLabel("Reason (required)", { exact: true }).fill("Principal is on leave this term; confirm the decision maker first");
  await form.getByRole("button", { name: /Record override/ }).click();
  await expect(panel.getByText("Reviewer override (machine said: contact now). Reason: Principal is on leave this term; confirm the decision maker first")).toBeVisible();
  await expect(panel.getByRole("list", { name: "Assessment history" }).getByRole("listitem")).toHaveCount(2);
  await expect(page.getByText("account.assessment_overridden", { exact: false })).toBeVisible();
});

test("QUALIFY-10 observer reads the assessment without controls", async ({ page }) => {
  await login(page, "observer");
  const panel = await openAccount(page);
  await expect(panel.getByRole("heading", { name: "Customer fit: strong" })).toBeVisible();
  await expect(panel.getByRole("button")).toHaveCount(0);
});

test("QUALIFY-10 override and history survive an api/web restart @after-restart", async ({ page }) => {
  await login(page, "operator");
  const panel = await openAccount(page);
  // Later specs may re-assess; the override must survive in the immutable history either way.
  const history = panel.getByRole("list", { name: "Assessment history" });
  await expect(history.getByText(/Revision 2 \(override\): investigate.*Principal is on leave this term/)).toBeVisible();
});
