// Dry runs (P4.5). Zero egress: every figure is simulated and no real message is ever sent.

export const SIMULATION_LABEL = "SIMULATION ONLY — 0 real messages sent";

export const SCENARIOS = [
  "all_allow",
  "opt_out_mid_run",
  "quiet_hours",
  "quota",
  "stale_approval",
  "provider_429_mock",
  "transport_timeout_mock",
  "worker_restart_mock",
] as const;

export type Share = { count: number; denominator: number; percent: number | null; kind: "simulated" };

export type SimulationReport = {
  label: string;
  considered: number;
  buckets: Record<"accepted" | "denied" | "deferred" | "invalid", Share>;
  lifecycle: Record<"sim_accepted" | "sim_delivered" | "sim_failed", Share>;
  reconciled: boolean;
  missing_prerequisites: Record<string, number>;
  standing_blockers: string[];
};

export type SimulationItem = {
  seq: number;
  account_id: string;
  account: string | null;
  bucket: "accepted" | "denied" | "deferred" | "invalid";
  reasons: string[];
  lifecycle: "sim_delivered" | "sim_failed" | "not_attempted";
  sim_receipt_id: string | null;
  attempts: number;
  draft_revision: number | null;
  approval_id: string | null;
  permission_revision: { id: string; version: number } | null;
  next_window_at: string | null;
};

export type SimulationRun = {
  id: string;
  campaign_id: string;
  scenario: string;
  mode: "fixture" | "readiness";
  status: "pending" | "running" | "completed" | "cancelled" | "failed";
  max_items: number;
  considered: number;
  real_messages_sent: 0;
  label: string;
  evaluated_at: string;
  policy_version: string;
  simulator_version: string;
  report: SimulationReport | null;
  report_digest: string | null;
  error_code: string | null;
  cancel_requested: boolean;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  items?: SimulationItem[];
};

export function share(s: Share): string {
  return `${s.count} of ${s.denominator}${s.percent === null ? "" : ` (${s.percent}%)`}, simulated`;
}
