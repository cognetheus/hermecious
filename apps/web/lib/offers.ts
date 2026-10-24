export type Readiness = "available" | "limited" | "planned" | "unverified" | "not_supported";

export const READINESS_LABEL: Record<Readiness, string> = {
  available: "Available",
  limited: "Limited",
  planned: "Planned",
  unverified: "Unverified",
  not_supported: "Not supported",
};

export type Claim = {
  capability_code: string;
  summary: string;
  readiness: Readiness;
  approved_for_sales: boolean;
  evidence_refs: string[];
  limitations: string[];
  approval_note: string | null;
};

export type Revision = {
  id: string;
  revision: number;
  state: "draft" | "published" | "retired";
  capability_version: string;
  capability_matrix: Claim[];
  approved_claims: Claim[];
  price_rules: { code: string; description: string; currency: string; amount: string; unit: string; approved: boolean }[];
  exclusions: string[];
  dependencies: string[];
  evidence_references: { ref: string; type: string; recorded_at: string; description: string }[];
  content_sha256: string;
  approved_at: string | null;
  published_at: string | null;
};

export type OfferSummary = {
  id: string;
  code: string;
  audience: string;
  status: "draft" | "published" | "archived";
  version: number;
  current_draft_revision: number | null;
  published_revision: number | null;
  updated_at: string;
};

export type OfferDetail = OfferSummary & { revisions: Revision[] };

/** The editable content of a revision, as accepted by POST /revisions. */
export function editableContent(revision: Revision | undefined): object {
  if (!revision) {
    return { capability_version: "", capability_matrix: [], price_rules: [], exclusions: [], dependencies: [], evidence_references: [] };
  }
  return {
    capability_version: revision.capability_version,
    capability_matrix: revision.capability_matrix,
    price_rules: revision.price_rules,
    exclusions: revision.exclusions,
    dependencies: revision.dependencies,
    evidence_references: revision.evidence_references,
  };
}
