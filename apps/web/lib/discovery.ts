// Discovery run and review types (P2.4). Every listing is unverified; nothing here is a qualified lead.

export type RunStatus = "pending" | "running" | "completed" | "partial" | "failed" | "cancelled";

export type Run = {
  id: string;
  status: RunStatus;
  version: number;
  provider: string;
  synthetic: boolean;
  area_label: string;
  city: string;
  attribution: string | null;
  rights_policy_version: string;
  budget: { max_candidates: number; max_search_pages: number; max_fetches: number; max_seconds: number };
  usage: Record<string, unknown>;
  examined_count: number;
  staged_count: number;
  rejected_count: number;
  displayed_count: number;
  truncated: boolean;
  stop_reason: string | null;
  partial_reason: string | null;
  error_code: string | null;
  review_counts: { pending: number; accepted: number; rejected: number; deferred: number };
  job_status: string | null;
  cancel_requested: boolean;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  exhaustive: false;
};

export type Match = {
  suggestion_id: string;
  status: string;
  version: number;
  resolution: "suggest_review" | "insufficient_evidence";
  reason_codes: string[];
  counterpart_kind: "candidate" | "account";
  counterpart_id: string;
  counterpart_name: string | null;
};

export type RunCandidate = {
  candidate_id: string;
  review_status: "pending" | "accepted" | "rejected" | "deferred";
  version: number;
  account_id: string | null;
  linked_account_id: string | null;
  review_note: string | null;
  provider: string;
  external_key: string;
  display_name: string;
  name_local: string | null;
  city: string;
  locality: string | null;
  location_precision: "point" | "area_center" | null;
  source_url: string | null;
  observed_at: string;
  upstream_timestamp: string | null;
  rights_policy_version: string;
  attribution: string | null;
  expires_at: string | null;
  expired: boolean;
  unknowns: string[];
  matches: Match[];
};

export type SourceOption = {
  provider: string;
  label: string;
  area_label: string;
  synthetic: boolean;
  rights_policy_version: string;
  attribution: string | null;
  licence_reference: string | null;
  storage: string;
  retention_days: number;
  max_candidates: number;
  request_quota: number;
};

export const ACTIVE: RunStatus[] = ["pending", "running"];

export function statusLabel(run: Pick<Run, "status" | "truncated" | "partial_reason" | "error_code">): string {
  switch (run.status) {
    case "pending":
      return "Queued";
    case "running":
      return "Running";
    case "completed":
      return run.truncated ? "Completed (bounded: more listings exist than this run took)" : "Completed (bounded run)";
    case "partial":
      return `Partial: ${run.partial_reason ?? "stopped early"}`;
    case "failed":
      return `Failed: ${run.error_code ?? "unknown error"}`;
    case "cancelled":
      return "Cancelled";
  }
}

const REASONS: Record<string, string> = {
  name_exact: "same name",
  name_near: "very similar name",
  same_locality: "same locality",
  coordinates_near: "map points within 150 m",
  co_located_different_names: "different names at the same map point",
  locality_unknown: "locality unknown",
  area_center_ambiguous: "map area centre is approximate",
  same_provider_distinct_ids: "the source lists them as separate places",
  no_comparable_name_script: "names are in different scripts",
  missing_city: "city unknown",
  shared_domain_weak: "shared website domain (weak; chains share domains)",
};

export function reasonText(code: string): string {
  return REASONS[code] ?? code.replaceAll("_", " ");
}

/** Only https links built by the API from validated keys are rendered as links. */
export function safeHttpsUrl(url: string | null): string | null {
  if (!url) return null;
  try {
    const parsed = new URL(url);
    return parsed.protocol === "https:" ? parsed.toString() : null;
  } catch {
    return null;
  }
}

export function newKey(prefix: string): string {
  return `${prefix}-${crypto.randomUUID()}`;
}
