import { type Cookie, expect, type Page } from "@playwright/test";

export const RUN = process.env.E2E_RUN_ID ?? "local";
export const PASSWORD = process.env.E2E_PASSWORD ?? "";
export const USERS = {
  owner: `owner-${RUN}@e2e.example`,
  operator: `operator-${RUN}@e2e.example`,
  observer: `observer-${RUN}@e2e.example`,
};

// One real login per role per Playwright process: the API's per-IP login limiter (30 / 15 min) is a security
// control, so the suite reuses each role's session cookie instead of logging in for every test.
const sessions = new Map<string, Cookie[]>();

export async function login(page: Page, who: keyof typeof USERS) {
  const cached = sessions.get(who);
  if (cached) {
    await page.context().addCookies(cached);
    await page.goto("/");
    if (await page.getByText("Signed in as").isVisible()) {
      return;
    }
    sessions.delete(who);
  }
  await page.goto("/login");
  await page.getByLabel("Email", { exact: true }).fill(USERS[who]);
  await page.getByLabel("Password", { exact: true }).fill(PASSWORD);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByText("Signed in as")).toBeVisible();
  sessions.set(who, await page.context().cookies());
}

export async function createAccount(page: Page, name: string, locality = "Johar Town") {
  await page.goto("/accounts/new");
  await page.getByLabel("School name", { exact: true }).fill(name);
  await page.getByLabel("Locality (optional)", { exact: true }).fill(locality);
  await page.getByRole("button", { name: "Create account" }).click();
  await expect(page.getByRole("heading", { level: 1, name })).toBeVisible();
}

/** Same-origin API call from the logged-in page, with a fresh in-memory CSRF token. */
export async function apiPost(page: Page, path: string, body: unknown): Promise<number> {
  return page.evaluate(
    async ({ path, body }) => {
      const csrf = (await (await fetch("/api/v1/auth/csrf")).json()).csrf_token as string;
      const response = await fetch(path, {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-CSRF-Token": csrf },
        body: JSON.stringify(body),
      });
      return response.status;
    },
    { path, body },
  );
}
