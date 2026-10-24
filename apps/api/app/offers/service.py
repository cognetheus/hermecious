"""Offer catalog services: drafts, revisions, owner publication, archive, sales-ready projection.

Every state change locks the offer row (SELECT ... FOR UPDATE) and compares
`expected_version` (optimistic CAS), so concurrent writers can never leave a
split-brain published revision. Revisions are append-only (DB trigger).
"""

import logging
import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.accounts.models import Vertical
from app.accounts.policy import PolicyViolation, clean_text
from app.auth.dependencies import ROLE_CAPABILITIES, Capability
from app.auth.models import Role
from app.auth.service import Actor
from app.core.clock import Clock
from app.core.errors import Conflict, Forbidden, InvalidRequest, NotFound
from app.offers import schemas
from app.offers.models import Offer, OfferRevision, OfferStatus, RevisionState

logger = logging.getLogger("app.offers")

STALE_VERSION = "Offer was changed by someone else; reload and retry"
NOT_SELLABLE = "Offer has no published, sellable revision"


def _require(actor: Actor, capability: Capability) -> None:
    if capability not in ROLE_CAPABILITIES[actor.role]:
        raise Forbidden()


def _offer(db: Session, actor: Actor, offer_id: uuid.UUID, *, lock: bool = False) -> Offer:
    query = select(Offer).where(Offer.id == offer_id, Offer.organization_id == actor.organization_id)
    offer = db.scalar(query.with_for_update() if lock else query)
    if offer is None:
        raise NotFound()
    return offer


def _locked_for_change(db: Session, actor: Actor, offer_id: uuid.UUID, expected_version: int) -> Offer:
    offer = _offer(db, actor, offer_id, lock=True)
    if offer.status == OfferStatus.ARCHIVED:
        db.rollback()
        raise Conflict("Archived offers cannot change")
    if offer.version != expected_version:
        db.rollback()
        raise Conflict(STALE_VERSION)
    return offer


def _bump(offer: Offer, clock: Clock) -> None:
    offer.version += 1
    offer.updated_at = clock.now()


def create_offer(db: Session, *, actor: Actor, clock: Clock, vertical_id: uuid.UUID, code: str, audience: str) -> Offer:
    _require(actor, Capability.MUTATE)
    vertical = db.get(Vertical, vertical_id)
    if vertical is None or vertical.status != "active":
        raise NotFound()
    try:
        audience = clean_text(audience, "audience", 200)
    except PolicyViolation as exc:
        raise InvalidRequest(str(exc)) from None
    now = clock.now()
    offer = Offer(
        organization_id=actor.organization_id,
        vertical_id=vertical.id,
        code=code,
        audience=audience,
        status=OfferStatus.DRAFT,
        version=1,
        created_at=now,
        updated_at=now,
    )
    db.add(offer)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise Conflict("An offer with this code already exists") from None
    logger.info("offer.created")
    return offer


def create_revision(
    db: Session,
    *,
    actor: Actor,
    clock: Clock,
    offer_id: uuid.UUID,
    expected_version: int,
    content: schemas.RevisionContent,
) -> OfferRevision:
    _require(actor, Capability.MUTATE)
    offer = _locked_for_change(db, actor, offer_id, expected_version)
    latest = db.scalar(select(func.max(OfferRevision.revision)).where(OfferRevision.offer_id == offer.id)) or 0
    if offer.current_draft_revision_id is not None:
        superseded = db.get(OfferRevision, offer.current_draft_revision_id)
        if superseded is not None and superseded.state == RevisionState.DRAFT:
            superseded.state = RevisionState.RETIRED  # never published; kept for history
    now = clock.now()
    revision = OfferRevision(
        organization_id=actor.organization_id,
        offer_id=offer.id,
        revision=latest + 1,
        state=RevisionState.DRAFT,
        capability_version=content.capability_version,
        approved_claims_json=[c.model_dump(mode="json") for c in content.approved_claims()],
        capability_matrix_json=[c.model_dump(mode="json") for c in content.capability_matrix],
        price_rules_json=[p.model_dump(mode="json") for p in content.price_rules],
        exclusions_json=list(content.exclusions),
        dependencies_json=list(content.dependencies),
        evidence_references_json=[e.model_dump(mode="json") for e in content.evidence_references],
        created_by=actor.user_id,
        content_sha256=content.digest(),
        created_at=now,
    )
    db.add(revision)
    db.flush()
    offer.current_draft_revision_id = revision.id
    _bump(offer, clock)
    db.commit()
    logger.info("offer.revision_created")
    return revision


def content_of(revision: OfferRevision) -> schemas.RevisionContent:
    return schemas.RevisionContent.model_validate(
        {
            "capability_version": revision.capability_version,
            "capability_matrix": revision.capability_matrix_json,
            "price_rules": revision.price_rules_json,
            "exclusions": revision.exclusions_json,
            "dependencies": revision.dependencies_json,
            "evidence_references": revision.evidence_references_json,
        }
    )


def publish(
    db: Session, *, actor: Actor, clock: Clock, offer_id: uuid.UUID, revision_number: int, expected_version: int
) -> OfferRevision:
    _require(actor, Capability.PUBLISH)
    offer = _locked_for_change(db, actor, offer_id, expected_version)
    revision = db.scalar(
        select(OfferRevision).where(OfferRevision.offer_id == offer.id, OfferRevision.revision == revision_number)
    )
    if revision is None:
        db.rollback()
        raise NotFound()
    if revision.state != RevisionState.DRAFT or revision.id != offer.current_draft_revision_id:
        db.rollback()
        raise Conflict("Only the current draft revision can be published")
    content = content_of(revision)
    if content.digest() != revision.content_sha256:  # stored content no longer matches its digest
        db.rollback()
        raise Conflict("Revision content failed its integrity check")
    try:
        schemas.assert_publishable(content)
    except schemas.PublicationRefused as exc:
        db.rollback()
        logger.info("offer.publication_refused")
        raise InvalidRequest(str(exc)) from None

    now = clock.now()
    if offer.published_revision_id is not None:
        previous = db.get(OfferRevision, offer.published_revision_id)
        if previous is not None and previous.state == RevisionState.PUBLISHED:
            previous.state = RevisionState.RETIRED
    revision.state = RevisionState.PUBLISHED
    revision.approved_by = actor.user_id
    revision.approved_at = now
    revision.published_at = now
    offer.published_revision_id = revision.id
    offer.current_draft_revision_id = None
    offer.status = OfferStatus.PUBLISHED
    _bump(offer, clock)
    db.commit()
    logger.info("offer.published")
    return revision


def archive(db: Session, *, actor: Actor, clock: Clock, offer_id: uuid.UUID, expected_version: int) -> Offer:
    _require(actor, Capability.PUBLISH)
    offer = _locked_for_change(db, actor, offer_id, expected_version)
    for revision_id in (offer.published_revision_id, offer.current_draft_revision_id):
        revision = db.get(OfferRevision, revision_id) if revision_id else None
        if revision is not None and revision.state in (RevisionState.PUBLISHED, RevisionState.DRAFT):
            revision.state = RevisionState.RETIRED  # history kept; no longer sellable
    offer.status = OfferStatus.ARCHIVED
    _bump(offer, clock)
    db.commit()
    logger.info("offer.archived")
    return offer


def list_offers(db: Session, *, actor: Actor) -> list[Offer]:
    _require(actor, Capability.READ)
    return list(db.scalars(select(Offer).where(Offer.organization_id == actor.organization_id).order_by(Offer.code)))


@dataclass(frozen=True)
class OfferDetail:
    offer: Offer
    revisions: list[OfferRevision]


def get_offer(db: Session, *, actor: Actor, offer_id: uuid.UUID) -> OfferDetail:
    _require(actor, Capability.READ)
    offer = _offer(db, actor, offer_id)
    query = select(OfferRevision).where(
        OfferRevision.organization_id == actor.organization_id, OfferRevision.offer_id == offer.id
    )
    if actor.role == Role.OBSERVER:  # observers see what was actually approved, not drafts
        query = query.where(OfferRevision.published_at.is_not(None))
    return OfferDetail(offer=offer, revisions=list(db.scalars(query.order_by(OfferRevision.revision))))


def sales_ready(db: Session, *, actor: Actor, offer_id: uuid.UUID) -> dict[str, Any]:
    """The only projection later message generators (P4/P6) may consume."""
    _require(actor, Capability.READ)
    offer = _offer(db, actor, offer_id)
    revision = db.get(OfferRevision, offer.published_revision_id) if offer.published_revision_id else None
    if offer.status != OfferStatus.PUBLISHED or revision is None or revision.state != RevisionState.PUBLISHED:
        raise Conflict(NOT_SELLABLE)
    content = content_of(revision)
    return {
        "offer_id": str(offer.id),
        "code": offer.code,
        "audience": offer.audience,
        "revision_id": str(revision.id),
        "revision": revision.revision,
        "content_sha256": revision.content_sha256,
        "capability_version": revision.capability_version,
        "published_at": revision.published_at.isoformat() if revision.published_at else None,
        "claims": [schemas.sales_claim(c) for c in content.approved_claims()],
        "exclusions": list(content.exclusions),
        "dependencies": list(content.dependencies),
        "pricing": schemas.pricing(revision.price_rules_json),
    }
