// Four-axis qualification (P3.3). Ordinal values only; contact_now is a research priority, never permission to send.

export type Level = "strong" | "moderate" | "weak" | "unknown";
export type Decision = "contact_now" | "investigate" | "nurture" | "exclude";

export type DimensionView = { value: Level; machine_value: Level; reason: string; fact_ids: string[]; questions: string[] };

export type AssessmentView = {
  id: string;
  revision: number;
  origin: "rubric" | "override";
  rubric_version: string;
  offer_id: string | null;
  capability_version: string | null;
  dimensions: Record<"customer_fit" | "need_evidence" | "accessibility" | "delivery_fit", DimensionView>;
  decision: Decision;
  machine_decision: Decision;
  decision_text: string;
  machine_reason: string;
  blocking: string[];
  questions: string[];
  channel_eligibility: "not_evaluated";
  override_reason: string | null;
  changed_fields: string[];
  created_at: string;
};

export type AssessmentsResponse = {
  latest: AssessmentView | null;
  needs_reassessment: boolean;
  history: { id: string; revision: number; origin: string; decision: Decision; changed_fields: string[]; override_reason: string | null; created_at: string }[];
};

export const DIMENSION_LABELS = {
  customer_fit: "Customer fit",
  need_evidence: "Need evidence",
  accessibility: "Accessibility",
  delivery_fit: "Delivery fit",
} as const;

export const DECISION_LABELS: Record<Decision, string> = {
  contact_now: "Research priority: contact candidate — channel eligibility not checked.",
  investigate: "Investigate: more evidence needed",
  nurture: "Nurture: documented deferral in force",
  exclude: "Exclude: documented disqualifier",
};
