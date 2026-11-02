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
