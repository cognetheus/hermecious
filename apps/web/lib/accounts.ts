export type AccountStatus =
  | "discovered"
  | "researching"
  | "assessed"
  | "shortlisted"
  | "investigate"
  | "nurture"
  | "excluded";

export const STATUSES: AccountStatus[] = [
  "discovered",
  "researching",
  "assessed",
  "shortlisted",
  "investigate",
  "nurture",
  "excluded",
];

export type Account = {
  id: string;
  vertical_id: string;
  canonical_name: string;
  normalized_name: string;
  city: string;
  locality: string | null;
  status: AccountStatus;
  version: number;
  discovered_at: string;
  updated_at: string;
};

export type Source = {
  id: string;
  provider: string;
  source_url: string;
  permitted_storage_class: string;
  rights_policy_version: string;
  observed_at: string;
  expires_at: string | null;
};

export type Fact = {
  id: string;
  claim_type: string;
  value: Record<string, unknown>;
  verification_status: "source_supported" | "hypothesis" | "disputed" | "rejected";
  confidence_label: "strong" | "moderate" | "weak" | "unknown";
  observed_at: string;
  expires_at: string | null;
  is_stale: boolean;
  is_current: boolean;
  evidence_excerpt: string | null;
  source: Source | null;
  supersedes_fact_id: string | null;
  superseded_by_fact_id: string | null;
  correction_reason: string | null;
  recorded_by: string | null;
  created_at: string;
};

export type Audit = {
  action_type: string;
  actor_user_id: string;
  details: Record<string, unknown>;
  request_id: string | null;
  recorded_at: string;
};

export type AccountDetail = Account & { aliases: string[]; facts: Fact[]; audits: Audit[] };

export const CLAIM_TEMPLATES: Record<string, Record<string, unknown>> = {
  campus_count: { count: 1 },
  school_levels: { levels: ["primary"] },
  ownership_type: { type: "unknown" },
  decision_authority: { holder: "unknown" },
  public_workflow_signal: { area: "admissions", signal: "" },
  software_in_use: { status: "unknown" },
  website_presence: { status: "unknown" },
  public_contact_channel: { channel: "website_form" },
};

export const PROVIDERS = ["manual_entry", "owner_seed_list", "first_party_website", "google_places"] as const;

// Display business time; the API speaks UTC.
export function karachiTime(iso: string | null): string {
  if (!iso) {
    return "none";
  }
  return new Intl.DateTimeFormat("en-GB", {
    timeZone: "Asia/Karachi",
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(iso));
}

export function verificationLabel(fact: Fact): string {
  if (fact.verification_status === "source_supported") {
    return fact.is_stale ? "Source-supported (STALE: re-verify)" : "Source-supported";
  }
  if (fact.verification_status === "hypothesis") {
    return "Hypothesis (not verified)";
  }
  return fact.verification_status;
}

export function describeValue(value: Record<string, unknown>): string {
  return Object.entries(value)
    .filter(([, v]) => v !== null && v !== undefined)
    .map(([k, v]) => `${k}: ${Array.isArray(v) ? v.join(", ") : String(v)}`)
    .join("; ");
}
