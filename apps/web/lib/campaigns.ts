// Campaign planning (P4.1). Internal planning only: nothing here authorizes contact.

export const NO_CONTACT = "Channel permission not checked — do not contact from this screen.";

export type CampaignSummary = { id: string; name: string; status: string; mode: "live" | "fixture"; revision: number; created_at: string };

export type Member = { account_id: string; name: string; stage: "approved_for_drafting" | "excluded"; reason: string; stale: string[]; drafting_blocked: boolean; decided_at: string };

export type CampaignView = CampaignSummary & {
  offer_id: string;
  capability_version: string;
  offer_current: boolean;
  rules: { decisions: string[] };
  budgets: { preview_limit: number; approvals_per_day: number; drafts_per_day: number };
  usage: Record<string, number>;
  members: Member[];
  approval_blocked_reason: string | null;
};

export type PreviewItem = {
  account_id: string;
  name: string;
  locality: string | null;
  provenance: string;
  qualifies: boolean;
  reasons: string[];
  decision: string | null;
  dimensions: Record<string, string> | null;
  stage: string | null;
  item_digest: string;
};

export type Preview = { preview_digest: string; total: number; qualifying: number; items: PreviewItem[]; approval_blocked_reason: string | null; mode: string };
