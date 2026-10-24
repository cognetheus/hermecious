// Evidence quality evaluation (P3.4). Fixtures prove the mechanism only; the production gate needs 30 real accounts.

export type EvalItem = {
  id: string;
  account_id: string;
  item_kind: "fact" | "signal" | "dimension";
  display_text: string;
  citations: { source_id: string | null; provider?: string; source_url?: string | null; expires_at?: string | null }[];
  real_provenance: boolean;
  eligibility_at_freeze: string;
  verdict: string | null;
  version: number;
  remediation_fact_id: string | null;
};

export type EvalRun = {
  id: string;
  kind: "baseline" | "post_remediation";
  baseline_run_id: string | null;
  state: "PASSED" | "FAILED" | "BLOCKED" | "INCOMPLETE" | "READY_TO_FINALIZE";
  result_reason: string | null;
  seed: string;
  corpus_fingerprint: string;
  corpus_status: string;
  accounts: number;
  real_accounts: number;
  synthetic_accounts: number;
  accounts_without_claims: number;
  items: number;
  pending: number;
  numerator: number | null;
  denominator: number | null;
  still_displayed_failures: number | null;
  version: number;
  created_at: string;
  finalized_at: string | null;
  item_list?: EvalItem[];
};

export type Gate = { enrollment_allowed: boolean; status: string; reason: string };
