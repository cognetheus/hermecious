"""Approval Studio API (P4.4). Owners/operators review (CSRF); every role reads.

`approve` is **content approval only**: simulation only, never consent, a queue entry, a template approval or a
send authorization. No route here queues, schedules or sends anything.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from app.api.dependencies import AppClock, AppSettings
from app.approvals import service
from app.approvals.models import DraftReview
from app.auth.dependencies import CurrentActor, allow_roles, authorize_request
from app.auth.models import Role
from app.drafts import service as drafts
from app.persistence.db import DbSession

router = APIRouter(prefix="/api/v1/drafts", tags=["approvals"], dependencies=[Depends(authorize_request)])
NO_STORE = {"Cache-Control": "no-store"}
Key = Annotated[str, Field(pattern=r"^[A-Za-z0-9._:-]{8,100}$")]
Digest = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
Reason = Annotated[str, Field(min_length=3, max_length=500)]


class _Body(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ApproveBody(_Body):
    content_digest: Digest
    contact_id: uuid.UUID | None = None
    template_ref: Annotated[str, Field(pattern=r"^[A-Za-z0-9_.:-]{3,80}$")] | None = None
    reason: Reason
    idempotency_key: Key


class RejectBody(_Body):
    content_digest: Digest
    reason: Reason
    idempotency_key: Key


class RevokeBody(_Body):
    approval_id: uuid.UUID
    reason: Reason
    idempotency_key: Key


def _respond(db: DbSession, review: DraftReview, created: bool) -> JSONResponse:
    body = service.receipt(db, review) | {"replayed": not created, "notice": service.NOTICE}
    return JSONResponse(body, status_code=201 if created else 200, headers=NO_STORE)


@router.post("/{draft_id}/approve")
@allow_roles(Role.OWNER, Role.OPERATOR)
def approve(
    draft_id: uuid.UUID, body: ApproveBody, actor: CurrentActor, db: DbSession, clock: AppClock, settings: AppSettings
) -> JSONResponse:
    review, created = service.approve(
        db,
        actor=actor,
        clock=clock,
        settings=settings,
        draft_id=draft_id,
        content_digest=body.content_digest,
        contact_id=body.contact_id,
        template_ref=body.template_ref,
        reason=body.reason,
        idempotency_key=body.idempotency_key,
    )
    return _respond(db, review, created)


@router.post("/{draft_id}/reject")
@allow_roles(Role.OWNER, Role.OPERATOR)
def reject(draft_id: uuid.UUID, body: RejectBody, actor: CurrentActor, db: DbSession, clock: AppClock) -> JSONResponse:
    review, created = service.reject(
        db,
        actor=actor,
        clock=clock,
        draft_id=draft_id,
        content_digest=body.content_digest,
        reason=body.reason,
        idempotency_key=body.idempotency_key,
    )
    return _respond(db, review, created)


@router.post("/{draft_id}/revoke-approval")
@allow_roles(Role.OWNER, Role.OPERATOR)
def revoke(draft_id: uuid.UUID, body: RevokeBody, actor: CurrentActor, db: DbSession, clock: AppClock) -> JSONResponse:
    review, created = service.revoke(
        db,
        actor=actor,
        clock=clock,
        draft_id=draft_id,
        approval_id=body.approval_id,
        reason=body.reason,
        idempotency_key=body.idempotency_key,
    )
    return _respond(db, review, created)


@router.get("/{draft_id}/reviews")
def reviews(
    draft_id: uuid.UUID, actor: CurrentActor, db: DbSession, clock: AppClock, settings: AppSettings
) -> JSONResponse:
    draft = drafts.get(db, actor.organization_id, draft_id)
    return JSONResponse(
        {
            "status": service.status(db, draft, clock.now(), settings),
            "items": service.history(db, draft),
            "notice": service.NOTICE,
        },
        headers=NO_STORE,
    )
