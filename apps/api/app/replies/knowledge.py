"""Approved-offer knowledge for reply proposals (P6.2, ADR-032). Read-only; one pinned offer revision.

Only the **currently published** revision of an offer in the caller's organization and vertical counts. Its sales
claims were validated at publication (P1.3 `assert_publishable`: sellable readiness, evidence, an approval note,
no delivery/SLA/guarantee/integration wording) and its price rules are approved with evidence. A claim whose newest
evidence is older than `EVIDENCE_MAX_AGE` is treated as expired and left out. Approved wording exists in English
only, so the only permitted reply locale is `en`.

No vector store, search engine, web access or historical revision is ever consulted.
"""

import hashlib
import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.accounts.models import Vertical
from app.offers import schemas
from app.offers import service as offer_service
from app.offers.models import Offer, OfferRevision

EVIDENCE_MAX_AGE = timedelta(days=365)
LOCALE = "en"
UNIT_LABEL = {"per_student_month": "per student per month", "per_campus_month": "per campus per month",
              "per_year": "per year", "one_time": "one time"}  # fmt: skip


def _digest(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()


@dataclass(frozen=True)
class ClaimRecord:
    key: str  # capability code
    summary: str
    readiness: str
    limitations: tuple[str, ...]
    digest: str


@dataclass(frozen=True)
class PriceRecord:
    key: str
    description: str
    amount: Decimal
    unit: str
    digest: str


@dataclass(frozen=True)
class Knowledge:
    offer_id: str | None = None
    revision: int | None = None
    content_sha256: str | None = None
    claims: tuple[ClaimRecord, ...] = ()
    prices: tuple[PriceRecord, ...] = ()
    excluded: tuple[str, ...] = field(default_factory=tuple)  # claim keys left out as expired

    @property
    def digests(self) -> set[str]:
        return {c.digest for c in self.claims} | {p.digest for p in self.prices}

    @property
    def claims_digest(self) -> str:
        return _digest([self.offer_id, self.revision, self.content_sha256, sorted(self.digests)])


def snapshot(db: Session, org: uuid.UUID, offer_id: uuid.UUID | None, now: datetime) -> Knowledge:
    """The approved knowledge of one published offer, or an empty snapshot (nothing may then be asserted)."""
    if offer_id is None:
        return Knowledge()
    offer = db.scalar(
        select(Offer)
        .join(Vertical, Vertical.id == Offer.vertical_id)
        .where(Offer.organization_id == org, Offer.id == offer_id, Offer.status == "published",
               Vertical.slug == "schools")
    )  # fmt: skip
    if offer is None or offer.published_revision_id is None:
        return Knowledge()
    revision = db.scalar(
        select(OfferRevision).where(
            OfferRevision.organization_id == org, OfferRevision.id == offer.published_revision_id,
            OfferRevision.state == "published",
        )
    )  # fmt: skip
    if revision is None:  # pragma: no cover  # composite FK and publication invariants
        return Knowledge()
    content = offer_service.content_of(revision)
    evidence = {e.ref: e.recorded_at for e in content.evidence_references}
    claims, excluded = [], []
    for claim in content.approved_claims():
        if claim.readiness not in schemas.SELLABLE_READINESS:  # pragma: no cover  # publication refuses these
            continue
        recorded = [evidence[r] for r in claim.evidence_refs if r in evidence]
        if not recorded or now - max(recorded) > EVIDENCE_MAX_AGE:
            excluded.append(claim.capability_code)
            continue
        body = {"offer": str(offer.id), "revision": revision.revision, "content": revision.content_sha256,
                "claim": schemas.sales_claim(claim)}  # fmt: skip
        claims.append(ClaimRecord(claim.capability_code, claim.summary, claim.readiness,
                                  tuple(claim.limitations), _digest(body)))  # fmt: skip
    prices = [
        PriceRecord(rule.code, rule.description, rule.amount, rule.unit,
                    _digest({"offer": str(offer.id), "revision": revision.revision,
                             "rule": rule.model_dump(mode="json")}))
        for rule in content.price_rules
        if rule.approved and rule.evidence_ref is not None
    ]  # fmt: skip
    return Knowledge(str(offer.id), revision.revision, revision.content_sha256, tuple(claims), tuple(prices),
                     tuple(excluded))  # fmt: skip


def published_offers(db: Session, org: uuid.UUID) -> list[uuid.UUID]:
    return list(
        db.scalars(
            select(Offer.id)
            .join(Vertical, Vertical.id == Offer.vertical_id)
            .where(Offer.organization_id == org, Offer.status == "published", Vertical.slug == "schools")
            .order_by(Offer.code)
        )
    )
