// School operations brief (P3.2): six keys, each observed / hypothesis / conflicting / unknown. Never a ranking.

export type SignalState = "observed" | "hypothesis" | "conflicting" | "unknown";

export type Signal = {
  key: string;
  state: SignalState;
  statement: string;
  caveat: string;
  question: string;
  fact_ids: string[];
  conflicting_fact_ids: string[];
  stale_fact_ids: string[];
  freshness: "current" | "aging" | "stale" | "none";
  evidence_at: string | null;
};

export type Citation = {
  claim_type: string;
  verification_status: string;
  observed_at: string;
  superseded: boolean;
  has_excerpt: boolean;
  source: { provider: string; source_url: string; storage_class: string; expires_at: string | null; expired: boolean } | null;
};

export type Snapshot = {
  id: string;
  rubric_version: string;
  signals: Record<string, Signal>;
  citations: Record<string, Citation>;
  linked_listings: number;
  created_at: string;
};

export type SignalsResponse = {
  latest: Snapshot | null;
  needs_reassessment: boolean;
  history: { id: string; created_at: string }[];
};

export const KEY_LABELS: Record<string, string> = {
  campus_footprint: "Campus footprint",
  operator_autonomy: "Operator autonomy",
  admissions_workflow: "Admissions workflow",
  fee_process: "Fee process",
  public_contact_route: "Public contact route",
  operational_complexity: "Operational complexity",
};

export const STATE_LABELS: Record<SignalState, string> = {
  observed: "Observed (cited source)",
  hypothesis: "Hypothesis (not verified)",
  conflicting: "Conflicting (sources disagree)",
  unknown: "Unknown",
};
