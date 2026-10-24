// Draft Studio (P4.2). A draft is never sendable and never approved here.

export const DRAFT_NOTICE = "DRAFT ONLY — NOT APPROVED FOR SENDING";

export type DraftSentence = {
  category: string;
  text: string;
  grounding: Record<string, string | null>;
  source?: { provider: string; rights_policy_version: string; source_url: string | null; expires_at: string | null; rights_current: boolean };
};

export type DraftView = {
  id: string;
  revision: number;
  mode: string;
  template_id: string;
  locale: string;
  contract_version: string;
  body_text: string;
  sentences: DraftSentence[];
  status: "needs_review" | "blocked_stale";
  stale_reasons: string[];
  capability_version: string;
  regenerate_reason: string | null;
  origin: "generated" | "edited";
  content_digest: string;
  latest: boolean;
  approval: ApprovalStatus;
  created_at: string;
};

// Approval Studio (P4.4). Content approval only: simulation only, never queued, sent or a template approval.
export type ReviewReceipt = {
  id: string;
  seq: number;
  decision: "approved_content" | "rejected" | "revoked";
  draft_revision: number;
  content_digest: string;
  contact_id: string | null;
  template_ref: string | null;
  eligibility_decision: string | null;
  reason: string;
  reviewer: string | null;
  reviewed_at: string;
  expires_at: string | null;
};

export type ApprovalStatus = {
  state: "not_reviewed" | "approved_content" | "approval_stale" | "rejected" | "revoked";
  stale_reasons: string[];
  review: ReviewReceipt | null;
  simulation_only: true;
  queued: false;
  sent: false;
  notice: string;
};

export function approvalLabel(status: ApprovalStatus): string {
  switch (status.state) {
    case "approved_content":
      return "Content approved (simulation only) — not queued, not sent, not a WhatsApp template approval";
    case "approval_stale":
      return `Approval stale — no longer valid: ${status.stale_reasons.join(", ")}`;
    case "rejected":
      return "Rejected";
    case "revoked":
      return "Approval revoked";
    default:
      return "Not reviewed";
  }
}
