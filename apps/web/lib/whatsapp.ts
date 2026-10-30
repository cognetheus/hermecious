// P5.3 WhatsApp test-send diagnostics (ADR-028). Shapes mirror apps/api/app/whatsapp/test_sends.py.
export const REAL_SEND_LABEL = "This will send a REAL WhatsApp message to my registered test number.";

export type ConnectionStatus = {
  mode: "simulation" | "contract_test" | "provider_test" | "production";
  graph_version: string;
  bound: boolean;
  phone_number_id: string | null;
  matches_configuration: boolean;
  test_outbound_enabled: boolean;
  test_sending_available: boolean;
  live_outbound_enabled: false;
  production_outreach: string;
};

export type Template = {
  id: string;
  template_id: string;
  name: string;
  language: string;
  category: string;
  provider_status: string;
  supported: boolean;
  body_text: string | null;
  body_parameter_count: number;
  header_parameter_count: number;
  fetched_at: string;
  fresh: boolean;
  usable_for_test: boolean;
};

export type TestRecipient = { id: string; label: string; address: string; status: "active" | "revoked" };

export type Delivery = { status: string; conflict: string | null } | null;

export type TestSend = {
  id: string;
  state: string;
  delivery: Delivery;
  created_at: string;
  real_message: true;
  label: string;
  // Absent for observers (redacted view).
  template?: { name: string; language: string; category: string };
  parameters?: string[];
  preview_text?: string | null;
  recipient?: string | null;
  preview_digest?: string;
  expires_at?: string;
  denial_reason?: string | null;
  provider_message_id?: string | null;
  provider_message_status?: string | null;
  error_class?: string | null;
  provider_error_code?: string | null;
  confirmed_at?: string | null;
  timeline?: { status: string; provider_timestamp: string; observed_at: string; error_code: string | null }[];
};

export type Preview = TestSend & { confirmation_nonce: string | null; replayed: boolean };

/** Acceptance is not delivery: only a signed webhook moves a message past `accepted_unknown_delivery`. */
export function deliveryLabel(delivery: Delivery): string {
  if (delivery === null) return "not sent";
  if (delivery.status === "accepted_unknown_delivery") return "accepted by Meta, delivery unknown (no webhook yet)";
  return delivery.conflict ? `${delivery.status} (conflict: ${delivery.conflict})` : delivery.status;
}
