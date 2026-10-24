// Account research types (P3.1). A proposed claim is never a fact until a reviewer accepts it.

export type ResearchSource = {
  id: string;
  provider: string;
  source_url: string | null;
  association?: string;
  storage_class: string;
  rights_policy_version: string;
  observed_at: string | null;
  expires_at: string | null;
  eligible?: boolean;
  ineligible_reason?: string | null;
  current_rights?: string;
};

export type ResearchClaim = {
  id: string;
  status: "proposed" | "accepted" | "rejected";
  version: number;
  claim_type: string;
  value: Record<string, unknown>;
  rule_id: string;
  extractor_version: string;
  language: string;
  locator: { start: number; end: number };
  excerpt: string | null;
  excerpt_withheld_reason: string | null;
  excerpt_policy: "stored" | "locator_only";
  source: ResearchSource;
  fact_id: string | null;
  review_reason: string | null;
};

export type ResearchRun = {
  id: string;
  status: "pending" | "running" | "completed" | "partial" | "failed" | "cancelled";
  version: number;
  source_record_ids: string[];
  extractor_version: string;
  sources_processed: number;
  sources_failed: number;
  claims_proposed: number;
  claims_abstained: number;
  partial_reason: string | null;
  error_code: string | null;
  cancel_requested: boolean;
  created_at: string;
  finished_at: string | null;
  observations?: { source: ResearchSource; status: string; reason_code: string | null; language: string | null; retrieved_at: string | null }[];
  claims?: ResearchClaim[];
};

export function runStatusText(run: ResearchRun): string {
  switch (run.status) {
    case "pending":
      return "Queued";
    case "running":
      return "Running";
    case "completed":
      return `Completed: ${run.claims_proposed} proposed claims from ${run.sources_processed} source(s)`;
    case "partial":
      return `Partial (${run.partial_reason ?? "stopped early"}): ${run.claims_proposed} proposed claims`;
    case "failed":
      return `Failed: ${run.error_code ?? "unknown error"}`;
    case "cancelled":
      return "Cancelled";
  }
}
