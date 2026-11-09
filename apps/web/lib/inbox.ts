// P5.4 read-only WhatsApp inbox (ADR-029). Shapes mirror apps/api/app/inbox/service.py.
export const READ_ONLY_LABEL = "READ ONLY — no replies or messages can be sent from the inbox";

export type Party = {
  type: "unmatched" | "contact" | "test_recipient";
  label: string;
  address: string;
  conflict: string | null;
  suppressed: boolean;
  environment: "test" | "production";
  account_id?: string;
};

export type Thread = {
  id: string;
  party: Party;
  last_activity_at: string;
  unread: number;
  last_inbound_seq: number;
  reviewed_through_seq: number;
  reviewed_at: string | null;
  version: number;
};

export const INTENT_LABELS = [
  "interested",
  "needs_details",
  "objection",
  "request_demo",
  "defer",
  "not_interested",
  "opt_out",
  "human_request",
  "ambiguous",
  "abusive",
] as const;

export type Intent = {
  observation_id: string;
  primary_intent: (typeof INTENT_LABELS)[number];
  secondary_intents: string[];
  safety_flags: string[];
  language: string;
  confidence: string;
  requires_human_review: boolean;
  recommended_action: string;
  evidence: { start: number; end: number; text: string; reason: string }[];
  reason_codes: string[];
  classifier_version: string;
  model_version: string | null;
  notice: string;
  review: { decision: string; corrected_primary: string | null; note: string; reviewed_at: string } | null;
};

export type InboundEntry = {
  type: "inbound";
  id: string;
  at: string;
  seq: number;
  kind: string;
  text: string | null;
  content: "available" | "not_retained" | "expired" | "unreadable" | "not_text";
  truncated: boolean;
  stop_signal: boolean;
  provenance: "verified_inbound";
  intent?: Intent | null;
  reply_proposals?: ReplyProposalView[];
};

export type ReplyProposalView = {
  id: string;
  version: number;
  stale: boolean;
  superseded: boolean;
  sent: false;
  label: string;
  created_at: string;
  rejected: { reason: string; at: string } | null;
  proposal: {
    status: "proposed" | "abstained";
    proposed_reply: string | null;
    language_fallback: boolean;
    inbound_language: string;
    recommended_action: string;
    escalate: boolean;
    citations: { kind: string; key: string; digest: string; sentence: number }[];
    confirmed_facts: { code: string; text: string; attribution: string; verified: false }[];
    open_questions: string[];
    missing_claims: string[];
    abstention_codes: string[];
    snapshot: { offer_id: string | null; offer_revision: number | null };
    composer_version: string;
    model_version: null;
  };
};

export type OutboundEntry = {
  type: "test_outbound";
  id: string;
  at: string;
  state: string;
  template: { name: string; language: string; category: string };
  provider_message_id: string | null;
  error_class: string | null;
  delivery: { status: string; conflict: string | null } | null;
  statuses: { status: string; at: string; error_code: string | null; provenance: "signed_webhook" }[];
  provenance: "provider_test";
};

export type Timeline = {
  thread: Thread;
  entries: (InboundEntry | OutboundEntry)[];
  before_cursor: string | null;
  reply_mode?: "off" | "fixtures" | "inbound";
  read_only: true;
};

export const CONTENT_LABEL: Record<InboundEntry["content"], string> = {
  available: "",
  not_retained: "Text not retained (no content key was configured when it arrived)",
  expired: "Text expired under the 90-day retention policy",
  unreadable: "Text cannot be read with the current keys",
  not_text: "Attachment or unsupported message (not downloaded)",
};

export function deliveryText(entry: OutboundEntry): string {
  if (entry.delivery === null) return entry.state.replaceAll("_", " ");
  if (entry.delivery.status === "accepted_unknown_delivery") return "accepted by Meta, delivery not confirmed by any webhook";
  return entry.delivery.conflict ? `${entry.delivery.status} (conflict: ${entry.delivery.conflict.replaceAll("_", " ")})` : entry.delivery.status;
}

export function words(code: string): string {
  return code.replaceAll("_", " ");
}

/** P6.3: who may act on a conversation. Auto replies do not exist yet; nothing here can send. */
export const OWNERSHIP_COMMANDS = [
  "takeover",
  "assign",
  "pause",
  "resolve",
  "release_to_agent",
  "open_handoff",
  "acknowledge_handoff",
  "block",
  "reopen",
] as const;
export const OWNERSHIP_REASONS = [
  "operator_takeover",
  "human_requested",
  "unknown_offer",
  "sensitive",
  "conflicting_facts",
  "unmatched_contact",
  "quality_concern",
  "resolved_by_operator",
  "agent_release_approved",
  "manual",
] as const;

export type Ownership = {
  thread_id: string;
  state: "new" | "agent_owned" | "human_owned" | "paused" | "blocked" | "resolved";
  owner_type: "none" | "agent" | "human";
  owner: string | null;
  owner_user_id: string | null;
  owner_generation: number;
  revision: number;
  auto_replies: "disabled";
  handoff: { id: string; reason: string; urgency: string; status: string; assigned_to: string | null; created_at: string } | null;
  history: { command: string; reason: string; from: string; to: string; generation: number; actor: string | null; at: string; canceled_attempts: number }[];
  attempts: { id: string; state: string; deny_reason: string | null; queued_generation: number; submitted_before_takeover: boolean }[];
  policy_version: string;
};

export type HandoffItem = {
  id: string;
  thread_id: string;
  address: string;
  reason: string;
  urgency: "normal" | "high";
  status: "open" | "acknowledged";
  assigned_to: string | null;
  created_at: string;
};

export const AUTO_REPLIES_LABEL = "AUTO REPLIES DISABLED — no automated reply exists; a person handles every conversation";
