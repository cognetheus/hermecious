"""Draft Studio API (P4.2). Owners/operators generate and regenerate (CSRF); every role reads.

Drafts are never sendable. No route approves, queues, schedules or sends anything.
"""

import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from app.api.dependencies import AppClock, AppSettings
from app.approvals import service as approvals
from app.auth.dependencies import CurrentActor, allow_roles, authorize_request
from app.auth.models import Role
from app.core.settings import Settings
from app.drafts import service
from app.drafts.models import Draft
from app.persistence.db import DbSession

router = APIRouter(prefix="/api/v1", tags=["drafts"], dependencies=[Depends(authorize_request)])
NO_STORE = {"Cache-Control": "no-store"}
Key = Annotated[str, Field(pattern=r"^[A-Za-z0-9._:-]{8,100}$")]
Template = Literal["school_introduction_v1", "school_question_v1"]


class GenerateBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    template_id: Template = "school_introduction_v1"
    locale: Annotated[str, Field(pattern=r"^[a-z]{2}(-[A-Za-z]{2,5}){0,2}$")] = "en-PK"
    idempotency_key: Key


class RegenerateBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: Annotated[str, Field(min_length=3, max_length=500)]
    idempotency_key: Key
    template_id: Template | None = None


class EditBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    edited_text: Annotated[str, Field(min_length=10, max_length=2000)]
    reason: Annotated[str, Field(min_length=3, max_length=500)]
    expected_revision: Annotated[int, Field(ge=1)]
    idempotency_key: Key


def _full(db: DbSession, draft: Draft, clock: AppClock, settings: Settings) -> dict[str, object]:
    """The draft plus its content-approval status, computed now from live dependencies."""
    now = clock.now()
    return service.view(db, draft, now, settings.environment) | {"approval": approvals.status(db, draft, now, settings)}


@router.post("/campaigns/{campaign_id}/accounts/{account_id}/drafts")
@allow_roles(Role.OWNER, Role.OPERATOR)
def generate(
    campaign_id: uuid.UUID,
    account_id: uuid.UUID,
    body: GenerateBody,
    actor: CurrentActor,
    db: DbSession,
    clock: AppClock,
    settings: AppSettings,
) -> JSONResponse:
    draft, created = service.generate(
        db,
        actor=actor,
        clock=clock,
        environment=settings.environment,
        campaign_id=campaign_id,
        account_id=account_id,
        template_id=body.template_id,
        locale=body.locale,
        idempotency_key=body.idempotency_key,
    )
    view = _full(db, draft, clock, settings) | {"replayed": not created}
    return JSONResponse(view, status_code=201 if created else 200, headers=NO_STORE)


@router.get("/campaigns/{campaign_id}/accounts/{account_id}/drafts")
def list_drafts(
    campaign_id: uuid.UUID,
    account_id: uuid.UUID,
    actor: CurrentActor,
    db: DbSession,
    clock: AppClock,
    settings: AppSettings,
) -> JSONResponse:
    drafts = service.list_for(db, actor.organization_id, campaign_id, account_id)
    items = [_full(db, d, clock, settings) for d in drafts]
    return JSONResponse({"items": items, "notice": service.NOTICE}, headers=NO_STORE)


@router.get("/drafts/{draft_id}")
def get_draft(
    draft_id: uuid.UUID, actor: CurrentActor, db: DbSession, clock: AppClock, settings: AppSettings
) -> JSONResponse:
    draft = service.get(db, actor.organization_id, draft_id)
    return JSONResponse(_full(db, draft, clock, settings), headers=NO_STORE)


@router.post("/drafts/{draft_id}/regenerate", status_code=201)
@allow_roles(Role.OWNER, Role.OPERATOR)
def regenerate(
    draft_id: uuid.UUID,
    body: RegenerateBody,
    actor: CurrentActor,
    db: DbSession,
    clock: AppClock,
    settings: AppSettings,
) -> JSONResponse:
    draft, created = service.regenerate(
        db,
        actor=actor,
        clock=clock,
        environment=settings.environment,
        draft_id=draft_id,
        reason=body.reason,
        idempotency_key=body.idempotency_key,
        template_id=body.template_id,
    )
    view = _full(db, draft, clock, settings) | {"replayed": not created}
    return JSONResponse(view, status_code=201 if created else 200, headers=NO_STORE)


@router.post("/drafts/{draft_id}/revisions", status_code=201)
@allow_roles(Role.OWNER, Role.OPERATOR)
def edit(
    draft_id: uuid.UUID,
    body: EditBody,
    actor: CurrentActor,
    db: DbSession,
    clock: AppClock,
    settings: AppSettings,
) -> JSONResponse:
    """A human edit: always a new immutable revision (older approvals no longer apply to it)."""
    draft, created = service.edit(
        db,
        actor=actor,
        clock=clock,
        environment=settings.environment,
        draft_id=draft_id,
        edited_text=body.edited_text,
        reason=body.reason,
        expected_revision=body.expected_revision,
        idempotency_key=body.idempotency_key,
    )
    view = _full(db, draft, clock, settings) | {"replayed": not created}
    return JSONResponse(view, status_code=201 if created else 200, headers=NO_STORE)
