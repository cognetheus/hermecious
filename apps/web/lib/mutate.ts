// Client components only: same-origin mutation with a freshly fetched, in-memory CSRF token.
export type ApiError = { error: { code: string; message: string; request_id: string; retryable: boolean } };

export async function postJson(
  path: string,
  body: unknown,
  method: "POST" | "PATCH" = "POST",
): Promise<{ ok: boolean; status: number; data: unknown }> {
  const csrf = await fetch("/api/v1/auth/csrf", { credentials: "same-origin", cache: "no-store" });
  if (!csrf.ok) {
    return { ok: false, status: csrf.status, data: await csrf.json() };
  }
  const { csrf_token: token } = (await csrf.json()) as { csrf_token: string };
  const response = await fetch(path, {
    method,
    credentials: "same-origin",
    headers: { "Content-Type": "application/json", "X-CSRF-Token": token },
    body: JSON.stringify(body),
  });
  return { ok: response.ok, status: response.status, data: await response.json() };
}

export function errorMessage(data: unknown): string {
  const error = (data as Partial<ApiError>)?.error;
  return error ? `${error.message} (${error.code})` : "Request failed";
}
