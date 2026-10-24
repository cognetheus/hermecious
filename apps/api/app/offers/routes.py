"""`/api/v1/offers/*` (P1.3). Authentication, CSRF and roles come from `authorize_request`."""

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from app.accounts.models import Vertical
from app.api.dependencies import AppClock
from app.auth.dependencies import Capability, CurrentActor, allow_roles, authorize_request, require_capability
from app.auth.models import Role
from app.auth.service import Actor
from app.core.errors import NotFound
from app.offers import schemas, service
from app.offers.models import Offer, OfferRevision
from app.persistence.db import DbSession

router = APIRouter(prefix="/api/v1/offers", tags=["offers"], dependencies=[Depends(authorize_request)])
Publisher = Annotated[Actor, Depends(require_capability(Capability.PUBLISH))]
NO_STORE = {"Cache-Control": "no-store"}


class _Body(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CreateOffer(_Body):
    vertical: Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]{1,79}$")] = "schools"
    code: Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]{2,99}$")]
    audience: Annotated[str, Field(min_length=1, max_length=200)]


class CreateRevision(_Body):
    expected_version: Annotated[int, Field(ge=1)]
    content: schemas.RevisionContent


class Publish(_Body):
    revision: Annotated[int, Field(ge=1)]
    expected_version: Annotated[int, Field(ge=1)]


class Archive(_Body):
    expected_version: Annotated[int, Field(ge=1)]


def offer_summary(offer: Offer, revisions: dict[uuid.UUID, int] | None = None) -> dict[str, Any]:
    numbers = revisions or {}
    return {
        "id": str(offer.id),
        "code": offer.code,
        "audience": offer.audience,
        "vertical_id": str(offer.vertical_id),
        "status": offer.status,
        "version": offer.version,
        "current_draft_revision": numbers.get(offer.current_draft_revision_id)
        if offer.current_draft_revision_id
        else None,
        "published_revision": numbers.get(offer.published_revision_id) if offer.published_revision_id else None,
        "updated_at": offer.updated_at.isoformat(),
    }


def revision_view(revision: OfferRevision) -> dict[str, Any]:
    return {
        "id": str(revision.id),
        "revision": revision.revision,
        "state": revision.state,
        "capability_version": revision.capability_version,
        "capability_matrix": revision.capability_matrix_json,
        "approved_claims": revision.approved_claims_json,
        "price_rules": revision.price_rules_json,
        "exclusions": revision.exclusions_json,
        "dependencies": revision.dependencies_json,
        "evidence_references": revision.evidence_references_json,
        "content_sha256": revision.content_sha256,
        "created_by": str(revision.created_by),
        "created_at": revision.created_at.isoformat(),
        "approved_by": str(revision.approved_by) if revision.approved_by else None,
        "approved_at": revision.approved_at.isoformat() if revision.approved_at else None,
        "published_at": revision.published_at.isoformat() if revision.published_at else None,
    }


def _revision_numbers(db: DbSession, actor: Actor) -> dict[uuid.UUID, int]:
    rows = db.execute(
        select(OfferRevision.id, OfferRevision.revision).where(OfferRevision.organization_id == actor.organization_id)
    ).all()
    return {row[0]: row[1] for row in rows}


@router.post("", status_code=201)
@allow_roles(Role.OWNER, Role.OPERATOR)
def create_offer(body: CreateOffer, actor: CurrentActor, db: DbSession, clock: AppClock) -> JSONResponse:
    vertical = db.scalar(select(Vertical).where(Vertical.slug == body.vertical))
    if vertical is None:
        raise NotFound()
    offer = service.create_offer(
        db, actor=actor, clock=clock, vertical_id=vertical.id, code=body.code, audience=body.audience
    )
    return JSONResponse(offer_summary(offer), status_code=201, headers=NO_STORE)


@router.get("")
def list_offers(actor: CurrentActor, db: DbSession) -> JSONResponse:
    numbers = _revision_numbers(db, actor)
    offers = service.list_offers(db, actor=actor)
    return JSONResponse({"offers": [offer_summary(o, numbers) for o in offers]}, headers=NO_STORE)


@router.get("/{offer_id}")
def get_offer(offer_id: uuid.UUID, actor: CurrentActor, db: DbSession) -> JSONResponse:
    detail = service.get_offer(db, actor=actor, offer_id=offer_id)
    numbers = {r.id: r.revision for r in detail.revisions}
    body = {**offer_summary(detail.offer, numbers), "revisions": [revision_view(r) for r in detail.revisions]}
    return JSONResponse(body, headers=NO_STORE)


@router.post("/{offer_id}/revisions", status_code=201)
@allow_roles(Role.OWNER, Role.OPERATOR)
def create_revision(
    offer_id: uuid.UUID, body: CreateRevision, actor: CurrentActor, db: DbSession, clock: AppClock
) -> JSONResponse:
    revision = service.create_revision(
        db, actor=actor, clock=clock, offer_id=offer_id, expected_version=body.expected_version, content=body.content
    )
    return JSONResponse(revision_view(revision), status_code=201, headers=NO_STORE)


@router.post("/{offer_id}/publish")
def publish(offer_id: uuid.UUID, body: Publish, actor: Publisher, db: DbSession, clock: AppClock) -> JSONResponse:
    revision = service.publish(
        db,
        actor=actor,
        clock=clock,
        offer_id=offer_id,
        revision_number=body.revision,
        expected_version=body.expected_version,
    )
    return JSONResponse(revision_view(revision), headers=NO_STORE)


@router.post("/{offer_id}/archive")
def archive(offer_id: uuid.UUID, body: Archive, actor: Publisher, db: DbSession, clock: AppClock) -> JSONResponse:
    offer = service.archive(db, actor=actor, clock=clock, offer_id=offer_id, expected_version=body.expected_version)
    return JSONResponse(offer_summary(offer, _revision_numbers(db, actor)), headers=NO_STORE)


@router.get("/{offer_id}/sales-ready")
def sales_ready(offer_id: uuid.UUID, actor: CurrentActor, db: DbSession) -> JSONResponse:
    return JSONResponse(service.sales_ready(db, actor=actor, offer_id=offer_id), headers=NO_STORE)
