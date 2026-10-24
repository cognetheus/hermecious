"""Typed offer revision content and the publishability rules (Batch 02 §P1.3.1).

Only `available`, or `limited` with explicit limitations, claims backed by
evidence references and an approval note can be published as sellable.
`planned` / `unverified` / `not_supported` may live in the internal matrix
but never reach the sales-ready projection. Text is plain text only.
"""

import hashlib
import json
import re
from datetime import datetime
from decimal import Decimal
from typing import Annotated, Any, Literal

from pydantic import AfterValidator, AwareDatetime, BaseModel, ConfigDict, Field, model_validator

_FORBIDDEN = re.compile("[\u0000-\u001f\u007f‪-‮⁦-⁩<>]")
# Commitments that must never be invented in sales copy: delivery timing, SLAs, guarantees, integrations.
_COMMITMENT = re.compile(
    r"(?i)\b(guarantee[ds]?|sla|uptime|go[- ]?live|deliver(?:ed|y)?\s+(?:in|within|by)|within\s+\d+\s*"
    r"(?:hours?|days?|weeks?|months?)|\d+(?:\.\d+)?\s*%\s*(?:uptime|availability)|integrat(?:es|ion|ed)\s+with)"
)

Readiness = Literal["available", "limited", "planned", "unverified", "not_supported"]
SELLABLE_READINESS = frozenset({"available", "limited"})
EvidenceType = Literal["internal-demo", "repo", "release-note", "owner-review"]
Code = Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]{2,63}$")]


def _plain(value: str) -> str:
    value = " ".join(value.split())
    if _FORBIDDEN.search(value):
        raise ValueError("must be plain text without markup or control characters")
    return value


def _text(max_length: int) -> Any:
    return Annotated[str, Field(min_length=1, max_length=max_length), AfterValidator(_plain)]


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class EvidenceReference(_Model):
    # Stable internal reference, e.g. "internal-demo:fees-2026-10". Plain URLs are not proof.
    ref: Annotated[str, Field(pattern=r"^(internal-demo|repo|release-note|owner-review):[A-Za-z0-9._/-]{1,120}$")]
    type: EvidenceType
    recorded_at: AwareDatetime
    description: _text(200)  # type: ignore[valid-type]

    @model_validator(mode="after")
    def _type_matches_ref(self) -> "EvidenceReference":
        if not self.ref.startswith(f"{self.type}:"):
            raise ValueError("evidence ref prefix must match its type")
        return self


class CapabilityClaim(_Model):
    capability_code: Code
    summary: _text(200)  # type: ignore[valid-type]
    readiness: Readiness
    approved_for_sales: bool = False
    evidence_refs: list[str] = Field(default_factory=list, max_length=10)
    limitations: list[_text(200)] = Field(default_factory=list, max_length=10)  # type: ignore[valid-type]
    approval_note: _text(500) | None = None  # type: ignore[valid-type]


class PriceRule(_Model):
    code: Code
    description: _text(200)  # type: ignore[valid-type]
    currency: Literal["PKR"]
    amount: Annotated[Decimal, Field(gt=0, max_digits=12, decimal_places=2)]
    unit: Literal["per_student_month", "per_campus_month", "per_year", "one_time"]
    approved: bool = False
    evidence_ref: str | None = None


class RevisionContent(_Model):
    capability_version: Annotated[str, Field(pattern=r"^[A-Za-z0-9._-]{1,80}$")]
    capability_matrix: list[CapabilityClaim] = Field(min_length=1, max_length=50)
    price_rules: list[PriceRule] = Field(default_factory=list, max_length=20)
    exclusions: list[_text(200)] = Field(default_factory=list, max_length=20)  # type: ignore[valid-type]
    dependencies: list[_text(200)] = Field(default_factory=list, max_length=20)  # type: ignore[valid-type]
    evidence_references: list[EvidenceReference] = Field(default_factory=list, max_length=50)

    @model_validator(mode="after")
    def _consistent(self) -> "RevisionContent":
        codes = [c.capability_code for c in self.capability_matrix]
        if len(codes) != len(set(codes)):
            raise ValueError("capability codes must be unique")
        if len({p.code for p in self.price_rules}) != len(self.price_rules):
            raise ValueError("price rule codes must be unique")
        known = {e.ref for e in self.evidence_references}
        if len(known) != len(self.evidence_references):
            raise ValueError("evidence refs must be unique")
        used = {r for c in self.capability_matrix for r in c.evidence_refs}
        used |= {p.evidence_ref for p in self.price_rules if p.evidence_ref}
        if not used <= known:
            raise ValueError("every referenced evidence must be listed in evidence_references")
        return self

    def approved_claims(self) -> list[CapabilityClaim]:
        """Claims the author proposes for sale; publication re-validates every one."""
        return [c for c in self.capability_matrix if c.approved_for_sales]

    def digest(self) -> str:
        canonical = json.dumps(self.model_dump(mode="json"), sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class PublicationRefused(ValueError):
    """The revision may not be published. The message is fixed text plus validated codes."""


def assert_publishable(content: RevisionContent) -> None:
    proposed = content.approved_claims()
    if not proposed:
        raise PublicationRefused("a revision needs at least one claim approved for sales")
    for claim in proposed:
        code = claim.capability_code
        if claim.readiness not in SELLABLE_READINESS:
            raise PublicationRefused(
                f"claim {code} has readiness {claim.readiness}; only available or limited can sell"
            )
        if not claim.evidence_refs:
            raise PublicationRefused(f"claim {code} has no evidence reference")
        if claim.approval_note is None:
            raise PublicationRefused(f"claim {code} has no approval note")
        if claim.readiness == "limited" and not claim.limitations:
            raise PublicationRefused(f"claim {code} is limited but lists no limitations")
        texts = [claim.summary, claim.approval_note, *claim.limitations]
        if any(_COMMITMENT.search(t) for t in texts):
            raise PublicationRefused(f"claim {code} contains a delivery, SLA, guarantee or integration commitment")
    for rule in content.price_rules:
        if not rule.approved or rule.evidence_ref is None:
            raise PublicationRefused(f"price rule {rule.code} is not approved with evidence")
        if _COMMITMENT.search(rule.description):
            raise PublicationRefused(f"price rule {rule.code} contains a delivery, SLA or guarantee commitment")


def sales_claim(claim: CapabilityClaim) -> dict[str, Any]:
    return {
        "capability_code": claim.capability_code,
        "summary": claim.summary,
        "readiness": claim.readiness,
        "limitations": list(claim.limitations),
        "evidence_refs": list(claim.evidence_refs),
    }


def pricing(rules: list[dict[str, Any]]) -> dict[str, Any]:
    if not rules:
        return {"status": "pricing_unavailable"}
    return {
        "status": "approved",
        "rules": [{k: r[k] for k in ("code", "description", "currency", "amount", "unit")} for r in rules],
    }


def parse_time(value: str | datetime) -> datetime:
    return value if isinstance(value, datetime) else datetime.fromisoformat(value)
