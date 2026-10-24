"""`campaign-rules-1.0` (P4.1, ADR-020): typed, bounded target rules and a pure candidate evaluation.

Rules are an allowlisted structure, never expressions or SQL. A candidate qualifies for **drafting review
only**. Unknown never satisfies a minimum, and an account's ownership or autonomy is never inferred from a
listing or brand.
"""

import hashlib
import json
import uuid
from dataclasses import dataclass, field
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field

RULES_VERSION = "campaign-rules-1.0"
RANK = {"unknown": 0, "weak": 1, "moderate": 2, "strong": 3}
DIMENSIONS = ("customer_fit", "need_evidence", "accessibility", "delivery_fit")
Place = Annotated[str, Field(min_length=1, max_length=120, pattern=r"^[\w .'-]+$")]
MinLevel = Literal["strong", "moderate", "weak"] | None


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Minimums(_Strict):
    customer_fit: MinLevel = None
    need_evidence: MinLevel = None
    accessibility: MinLevel = None
    delivery_fit: MinLevel = None


class TargetRules(_Strict):
    decisions: Annotated[list[Literal["contact_now", "investigate"]], Field(min_length=1, max_length=2)] = [
        "contact_now"
    ]
    minimums: Minimums = Minimums()
    localities_include: Annotated[list[Place], Field(max_length=20)] = []
    localities_exclude: Annotated[list[Place], Field(max_length=20)] = []
    exclude_account_ids: Annotated[list[uuid.UUID], Field(max_length=100)] = []


class Budgets(_Strict):
    """Local planning budgets (downward-only). These are not channel or WhatsApp limits."""

    preview_limit: Annotated[int, Field(ge=1, le=30)] = 30
    approvals_per_day: Annotated[int, Field(ge=0, le=10)] = 10
    drafts_per_day: Annotated[int, Field(ge=0, le=10)] = 10


def rules_digest(rules: TargetRules) -> str:
    canonical = json.dumps({"version": RULES_VERSION, "rules": rules.model_dump(mode="json")}, sort_keys=True)
    return hashlib.sha256(canonical.encode()).hexdigest()


@dataclass(frozen=True)
class Candidate:
    account_id: str
    name: str
    city: str
    locality: str | None
    archived: bool
    provenance: str  # real | synthetic | unsourced
    assessment: dict[str, Any] | None  # {id, revision, decision, dims{...}, offer_revision_id, needs_reassessment}
    manual_stage: str | None  # approved_for_drafting | excluded | None


@dataclass
class Evaluation:
    qualifies: bool
    reasons: list[str] = field(default_factory=list)


def evaluate(c: Candidate, rules: TargetRules, offer_revision_id: str, mode: str) -> Evaluation:
    reasons: list[str] = []
    if c.manual_stage == "excluded" or uuid.UUID(c.account_id) in set(rules.exclude_account_ids):
        reasons.append("manually_excluded")
    if c.archived:
        reasons.append("account_archived")
    if c.city != "Lahore":
        reasons.append("other_city")
    locality = (c.locality or "").casefold()
    if rules.localities_include and locality not in {p.casefold() for p in rules.localities_include}:
        reasons.append("locality_not_targeted" if locality else "locality_unknown")
    if locality and locality in {p.casefold() for p in rules.localities_exclude}:
        reasons.append("locality_excluded")
    if mode == "fixture" and c.provenance != "synthetic":
        reasons.append("real_account_in_fixture_campaign")
    if mode == "live" and c.provenance != "real":
        reasons.append(f"{c.provenance}_account")
    a = c.assessment
    if a is None:
        reasons.append("unassessed")
    else:
        if a["needs_reassessment"]:
            reasons.append("stale_assessment")
        if a["offer_revision_id"] != offer_revision_id:
            reasons.append("assessed_against_other_offer")
        if a["decision"] in ("exclude", "nurture"):
            reasons.append(f"decision_{a['decision']}")
        elif a["decision"] not in rules.decisions:
            reasons.append("decision_not_targeted")
        for dim in DIMENSIONS:
            minimum = getattr(rules.minimums, dim)
            if minimum is not None and RANK[a["dims"][dim]] < RANK[minimum]:
                reasons.append(f"below_minimum:{dim}")  # unknown (rank 0) never meets a minimum
    return Evaluation(not reasons, reasons)


def item_digest(c: Candidate, rules_digest_value: str, offer_revision_id: str) -> str:
    payload = {
        "account": c.account_id,
        "assessment": c.assessment,
        "stage": c.manual_stage,
        "rules": rules_digest_value,
        "offer": offer_revision_id,
        "provenance": c.provenance,
        "archived": c.archived,
        "locality": c.locality,
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()
