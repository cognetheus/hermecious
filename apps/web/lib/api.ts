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
