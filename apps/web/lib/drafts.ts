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
  created_at: string;
};
