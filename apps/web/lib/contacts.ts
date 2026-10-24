// Contacts, permission evidence and channel eligibility (P4.3). Simulation only: nothing here sends.

export const ELIGIBILITY_NOTICE = "Simulation eligibility only — sending disabled";

export const CONTACT_ROLES = ["school_office", "admissions_office", "accounts_office", "principal_office"] as const;
export const CAPTURE_METHODS = ["signed_paper_form", "web_form_checkbox", "whatsapp_opt_in_reply", "recorded_call"] as const;
export const PROOF_KINDS = ["form_serial", "web_submission_id", "message_id", "call_recording_id"] as const;
export const SUPPRESSION_REASONS = ["opt_out", "complaint", "owner_request", "wrong_number"] as const;

export type Permission = {
  id: string;
  purpose: "marketing" | "utility";
  channel: string;
  status: "pending" | "verified" | "rejected" | "revoked" | "superseded";
  version: number;
  expires_at: string;
  // Owners and operators only (observers see the status fields above).
  business_name?: string;
  capture_method?: string;
  consent_wording_version?: string;
  proof?: { kind: string; reference: string; key_id: string };
  captured_at?: string;
  recorded_at?: string;
  recorded_by?: string | null;
  reviewed_by?: string | null;
  reviewed_at?: string | null;
  review_reason?: string | null;
  revoked_by?: string | null;
  revoked_at?: string | null;
  revoke_reason?: string | null;
};

export type ContactView = {
  id: string;
  account_id: string;
  channel: string;
  role: string;
  address: string;
  suppressed: boolean;
  suppression: { reason: string; created_at: string } | null;
  permissions: Permission[];
};

export type PolicyInfo = {
  policy_version: string;
  business_name: string;
  consent_wording: Record<string, string>;
  fixtures: {
    templates: { id: string; category: string; provider_status: string; locale: string }[];
    inbound: { id: string; received_at: string; text_kind: string }[];
  };
};

export type Decision = {
  decision: "allow_for_simulation" | "deny" | "defer";
  reasons: { code: string; explanation: string }[];
  policy_version: string;
  permission_revision: { id: string; version: number } | null;
  suppression_revision: number;
  evaluated_at: string;
  next_window_at: string | null;
  live_send_authorized: false;
};

// A `datetime-local` value is read as Asia/Karachi wall time (UTC+05:00, no daylight saving).
export function karachiInputToIso(value: string): string {
  return `${value}:00+05:00`;
}
