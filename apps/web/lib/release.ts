// P5.5 production readiness (ADR-030). Shapes mirror apps/api/app/release.
export type CheckStatus = "VERIFIED" | "FAILED" | "UNKNOWN" | "BLOCKED_EXTERNAL";

export type Check = { code: string; status: CheckStatus; evidence_ref: string | null; reason: string; owner: string };

export type Assessment = {
  id: string;
  status: "no_go" | "blocked_external" | "ready_for_operator_review";
  digest: string;
  checks: Check[];
  identity: { waba: string | null; phone: string | null; mode: string | null };
  environment: string;
  build_sha: string | null;
  checked_at: string;
  expires_at: string;
  fresh: boolean;
  grants_sending: false;
};

export type Attestation = { id: string; kind: string; statement: string; evidence_ref: string; attested_at: string; expires_at: string; current: boolean };

export type Authorization = {
  id: string;
  status: "active" | "paused" | "revoked";
  pause_reason: string | null;
  purpose: string;
  max_per_day: number;
  assessment_id: string;
  created_at: string;
  expires_at: string;
  expired: boolean;
};

export type Readiness = {
  assessment: Assessment | null;
  attestations: Attestation[];
  authorizations: Authorization[];
  live_gate: string;
  banner: string;
  acknowledgement: string;
  pilot_label: string;
};

export const STATUS_LABEL: Record<Assessment["status"], string> = {
  no_go: "NO GO",
  blocked_external: "BLOCKED (external prerequisites missing)",
  ready_for_operator_review: "Ready for owner review (this is not permission to send)",
};

export const ATTESTATION_KINDS = [
  ["meta_business_verification", "Meta business verification"],
  ["pakistan_legal_review", "Pakistan-local legal review"],
  ["real_test_receipt", "Real test receipt (WATEST-10, from the test deployment)"],
  ["operations_readiness", "Monitoring, backups, kill switch and rollback drill"],
] as const;
