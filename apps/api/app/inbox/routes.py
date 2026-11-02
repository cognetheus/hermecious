"""Read-only WhatsApp inbox API (P5.4, ADR-029).

Owners and operators read threads and timelines and mark a thread reviewed; observers get 403, because message
content is business correspondence. An owner may enqueue a rebuild. Nothing here can reply, send, enroll a
contact or record consent.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from app.api.dependencies import AppClock, AppSettings
from app.auth.dependencies import CurrentActor, allow_roles, authorize_request
from app.auth.models import Role
from app.inbox import service
from app.persistence.db import DbSession
from app.whatsapp import content

router = APIRouter(prefix="/api/v1/inbox/whatsapp", tags=["inbox"], dependencies=[Depends(authorize_request)])
PRIVATE = {"Cache-Control": "private, no-store"}
Cursor = Annotated[str | None, Query(max_length=200)]


class ReviewBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    through_seq: Annotated[int, Field(ge=1, le=2**62)]


@router.get("/threads")
@allow_roles(Role.OWNER, Role.OPERATOR)
def threads(
    actor: CurrentActor, db: DbSession, cursor: Cursor = None, limit: Annotated[int, Query(ge=1, le=50)] = 25
) -> JSONResponse:
    return JSONResponse(service.threads_page(db, actor.organization_id, cursor=cursor, limit=limit), headers=PRIVATE)


@router.get("/threads/{thread_id}")
@allow_roles(Role.OWNER, Role.OPERATOR)
def thread(
    thread_id: uuid.UUID,
    actor: CurrentActor,
    db: DbSession,
    clock: AppClock,
    settings: AppSettings,
    before: Cursor = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> JSONResponse:
    page = service.timeline(
        db, actor.organization_id, thread_id, before=before, limit=limit, keys=content.keyring(settings),
        now=clock.now(),
    )  # fmt: skip
    return JSONResponse(page, headers=PRIVATE)


@router.post("/threads/{thread_id}/review")
@allow_roles(Role.OWNER, Role.OPERATOR)
def review(thread_id: uuid.UUID, body: ReviewBody, actor: CurrentActor, db: DbSession, clock: AppClock) -> JSONResponse:
    row, changed = service.mark_reviewed(
        db, actor=actor, clock=clock, thread_id=thread_id, through_seq=body.through_seq
    )
    payload = {"id": str(row.id), "reviewed_through_seq": row.reviewed_through_seq, "version": row.version,
               "changed": changed}  # fmt: skip
    return JSONResponse(payload, headers=PRIVATE)


@router.post("/rebuild", status_code=202)
def rebuild(actor: CurrentActor, db: DbSession, clock: AppClock, settings: AppSettings) -> JSONResponse:
    """Owner only. Recomputes threads from the signed source tables in the worker; reads only."""
    job_id = service.request_rebuild(db, actor=actor, clock=clock, environment=settings.environment)
    return JSONResponse({"job_id": str(job_id)}, status_code=202, headers=PRIVATE)
