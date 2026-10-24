import { cookies } from "next/headers";
import { redirect } from "next/navigation";

// Server-side base URL of the API (inside the Compose network by default).
export function apiInternalUrl(): string {
  return process.env.API_INTERNAL_URL ?? "http://api:8000";
}

export type CurrentUser = {
  id: string;
  display_name: string | null;
  email: string;
  role: "owner" | "operator" | "observer";
  organization_id: string;
};

/** Server components only: GET an API path with the caller's session; 401 redirects to /login. */
export async function apiGet<T>(path: string): Promise<{ status: number; body: T }> {
  const cookieHeader = (await cookies()).toString();
  const response = await fetch(`${apiInternalUrl()}${path}`, {
    headers: cookieHeader ? { cookie: cookieHeader } : {},
    cache: "no-store",
  });
  if (response.status === 401) {
    redirect("/login");
  }
  return { status: response.status, body: (await response.json()) as T };
}
