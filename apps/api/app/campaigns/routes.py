"""`/api/v1/campaigns` (P4.1): internal campaign planning. Owners/operators change (CSRF); every role reads.

No route here sends, schedules, enrolls for messaging or records contact permission.
"""

import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from app.api.dependencies import AppClock, AppSettings
from app.auth.dependencies import CurrentActor, allow_roles, authorize_request
from app.auth.models import Role
from app.campaigns import rules as campaign_rules
from app.campaigns import service
from app.campaigns.models import Campaign
from app.persistence.db import DbSession

router = APIRouter(prefix="/api/v1/campaigns", tags=["campaigns"], dependencies=[Depends(authorize_request)])
NO_STORE = {"Cache-Control": "no-store"}
Key = Annotated[str, Field(pattern=r"^[A-Za-z0-9._:-]{8,100}$")]
Name = Annotated[str, Field(min_length=3, max_length=120)]


class _Body(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CreateBody(_Body):
    name: Name
    offer_id: uuid.UUID
    mode: Literal["live", "fixture"] = "live"
    district: Annotated[str, Field(min_length=1, max_length=160)] | None = None
    rules: campaign_rules.TargetRules = campaign_rules.TargetRules()
    budgets: campaign_rules.Budgets = campaign_rules.Budgets()


class UpdateBody(_Body):
    expected_revision: Annotated[int, Field(ge=1)]
    name: Name | None = None
    rules: campaign_rules.TargetRules | None = None
    budgets: campaign_rules.Budgets | None = None
    repin_offer: bool = False


class TransitionBody(_Body):
    expected_revision: Annotated[int, Field(ge=1)]


class ApproveBody(_Body):
    expected_revision: Annotated[int, Field(ge=1)]
    item_digest: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
    idempotency_key: Key
    reason: Annotated[str, Field(min_length=3, max_length=500)] = "Reviewed: qualifies for drafting review"


class ExcludeBody(_Body):
    reason: Annotated[str, Field(min_length=3, max_length=500)]
    idempotency_key: Key


@router.post("", status_code=201)
@allow_roles(Role.OWNER, Role.OPERATOR)
def create(
    body: CreateBody, actor: CurrentActor, db: DbSession, clock: AppClock, settings: AppSettings
) -> JSONResponse:
    campaign = service.create(
        db,
        actor=actor,
        clock=clock,
        environment=settings.environment,
        name=body.name,
        offer_id=body.offer_id,
        mode=body.mode,
        district=body.district,
        target=body.rules,
        budgets=body.budgets,
    )
    return JSONResponse(
        service.view(db, campaign, clock.now(), settings.environment), status_code=201, headers=NO_STORE
    )


@router.get("")
def list_campaigns(actor: CurrentActor, db: DbSession) -> JSONResponse:
    rows = db.scalars(
        select(Campaign)
        .where(Campaign.organization_id == actor.organization_id)
        .order_by(Campaign.created_at.desc())
        .limit(50)
    )
    items = [
        {
            "id": str(c.id),
            "name": c.name,
            "status": c.status,
            "mode": c.mode,
            "revision": c.revision,
            "created_at": c.created_at.isoformat(),
        }
        for c in rows
    ]
    return JSONResponse({"items": items, "notice": service.NO_CONTACT_NOTICE}, headers=NO_STORE)


@router.get("/{campaign_id}")
def get_campaign(
    campaign_id: uuid.UUID, actor: CurrentActor, db: DbSession, clock: AppClock, settings: AppSettings
) -> JSONResponse:
    campaign = service._campaign(db, actor.organization_id, campaign_id)
    return JSONResponse(service.view(db, campaign, clock.now(), settings.environment), headers=NO_STORE)


@router.patch("/{campaign_id}")
@allow_roles(Role.OWNER, Role.OPERATOR)
def update(
    campaign_id: uuid.UUID,
    body: UpdateBody,
    actor: CurrentActor,
    db: DbSession,
    clock: AppClock,
    settings: AppSettings,
) -> JSONResponse:
    campaign = service.update(
        db,
        actor=actor,
        clock=clock,
        campaign_id=campaign_id,
        expected_revision=body.expected_revision,
        name=body.name,
        target=body.rules,
        budgets=body.budgets,
        repin_offer=body.repin_offer,
    )
    return JSONResponse(service.view(db, campaign, clock.now(), settings.environment), headers=NO_STORE)


@router.get("/{campaign_id}/preview")
def preview(
    campaign_id: uuid.UUID,
    actor: CurrentActor,
    db: DbSession,
    clock: AppClock,
    settings: AppSettings,
    limit: Annotated[int, Query(ge=1, le=30)] = 30,
    cursor: Annotated[int, Query(ge=0, le=500)] = 0,
    digest: Annotated[str | None, Query(pattern=r"^[0-9a-f]{64}$")] = None,
) -> JSONResponse:
    body = service.preview(
        db,
        org=actor.organization_id,
        campaign_id=campaign_id,
        now=clock.now(),
        environment=settings.environment,
        limit=limit,
        cursor=cursor,
        expected_digest=digest,
    )
    return JSONResponse(body, headers=NO_STORE)


def _transition(action: str):  # type: ignore[no-untyped-def]
    @allow_roles(Role.OWNER, Role.OPERATOR)
    def endpoint(
        campaign_id: uuid.UUID,
        body: TransitionBody,
        actor: CurrentActor,
        db: DbSession,
        clock: AppClock,
        settings: AppSettings,
    ) -> JSONResponse:
        campaign = service.transition(
            db,
            actor=actor,
            clock=clock,
            environment=settings.environment,
            campaign_id=campaign_id,
            action=action,
            expected_revision=body.expected_revision,
        )
        return JSONResponse(service.view(db, campaign, clock.now(), settings.environment), headers=NO_STORE)

    endpoint.__name__ = f"campaign_{action}"
    return endpoint


for _action in ("activate", "pause", "cancel"):
    router.post(f"/{{campaign_id}}/{_action}")(_transition(_action))


@router.post("/{campaign_id}/candidates/{account_id}/approve")
@allow_roles(Role.OWNER, Role.OPERATOR)
def approve(
    campaign_id: uuid.UUID,
    account_id: uuid.UUID,
    body: ApproveBody,
    actor: CurrentActor,
    db: DbSession,
    clock: AppClock,
    settings: AppSettings,
) -> JSONResponse:
    outcome = service.approve(
        db,
        actor=actor,
        clock=clock,
        environment=settings.environment,
        campaign_id=campaign_id,
        account_id=account_id,
        expected_revision=body.expected_revision,
        item_digest=body.item_digest,
        idempotency_key=body.idempotency_key,
        reason=body.reason,
    )
    return JSONResponse(outcome | {"contact_authorized": False, "notice": service.NO_CONTACT_NOTICE}, headers=NO_STORE)


@router.post("/{campaign_id}/candidates/{account_id}/exclude")
@allow_roles(Role.OWNER, Role.OPERATOR)
def exclude(
    campaign_id: uuid.UUID,
    account_id: uuid.UUID,
    body: ExcludeBody,
    actor: CurrentActor,
    db: DbSession,
    clock: AppClock,
) -> JSONResponse:
    outcome = service.exclude(
        db,
        actor=actor,
        clock=clock,
        campaign_id=campaign_id,
        account_id=account_id,
        reason=body.reason,
        idempotency_key=body.idempotency_key,
    )
    return JSONResponse(outcome, headers=NO_STORE)
