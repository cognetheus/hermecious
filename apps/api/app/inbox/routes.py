"""Read-only WhatsApp inbox API (P5.4, ADR-029).

Owners and operators read threads and timelines and mark a thread reviewed; observers get 403, because message
content is business correspondence. An owner may enqueue a rebuild. Nothing here can reply, send, enroll a
contact or record consent.
"""

import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from app.api.dependencies import AppClock, AppSettings
from app.auth.dependencies import CurrentActor, allow_roles, authorize_request
from app.auth.models import Role
from app.inbox import service
from app.intent import service as intent
from app.persistence.db import DbSession
from app.replies import service as replies
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
    page["reply_mode"] = settings.reply_proposals  # P6.2: off | fixtures | inbound
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


class IntentReviewBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    observation_id: uuid.UUID
    decision: Literal["confirmed", "corrected"]
    corrected_primary: Literal[
        "interested", "needs_details", "objection", "request_demo", "defer", "not_interested", "opt_out",
        "human_request", "ambiguous", "abusive",
    ] | None = None  # fmt: skip
    note: Annotated[str, Field(max_length=500)] = ""


@router.post("/messages/{message_id}/intent-review", status_code=201)
@allow_roles(Role.OWNER, Role.OPERATOR)
def intent_review(
    message_id: uuid.UUID, body: IntentReviewBody, actor: CurrentActor, db: DbSession, clock: AppClock
) -> JSONResponse:
    """P6.1: the operator's own judgement of an intent observation. Stored apart and audited; changes nothing else."""
    row = intent.review(
        db, actor=actor, clock=clock, message_id=message_id, observation_id=body.observation_id,
        decision=body.decision, corrected_primary=body.corrected_primary, note=body.note,
    )  # fmt: skip
    payload = {"id": str(row.id), "decision": row.decision, "corrected_primary": row.corrected_primary}
    return JSONResponse(payload, status_code=201, headers=PRIVATE)


@router.post("/intent/backfill", status_code=202)
def intent_backfill(actor: CurrentActor, db: DbSession, clock: AppClock, settings: AppSettings) -> JSONResponse:
    """Owner only: classify signed inbound messages that lack an observation for the current classifier version."""
    job_id = intent.request_backfill(db, actor=actor, clock=clock, environment=settings.environment)
    return JSONResponse({"job_id": str(job_id)}, status_code=202, headers=PRIVATE)


class ProposalBody(BaseModel):
    model_config = ConfigDict(extra="forbid")  # recipient, tool, campaign, send ... are refused
    offer_id: uuid.UUID | None = None
    conversation_id: uuid.UUID | None = None


class RejectBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: Annotated[str, Field(min_length=3, max_length=500)]


@router.post("/messages/{message_id}/reply-proposals")
@allow_roles(Role.OWNER, Role.OPERATOR)
def propose_reply(
    message_id: uuid.UUID, body: ProposalBody, actor: CurrentActor, db: DbSession, clock: AppClock,
    settings: AppSettings,
) -> JSONResponse:  # fmt: skip
    """P6.2: a grounded draft or an abstention for human review. It is never sent and changes no other state."""
    row, created = replies.generate(
        db, actor=actor, clock=clock, settings=settings, message_id=message_id, offer_id=body.offer_id,
        conversation_id=body.conversation_id,
    )  # fmt: skip
    lineage = replies.views(db, actor.organization_id, [row.inbound_message_id], content.keyring(settings),
                            clock.now())[row.inbound_message_id]  # fmt: skip
    return JSONResponse(next(p for p in lineage if p["id"] == str(row.id)), status_code=201 if created else 200,
                        headers=PRIVATE)  # fmt: skip


@router.get("/messages/{message_id}/reply-proposals")
@allow_roles(Role.OWNER, Role.OPERATOR)
def reply_proposals(
    message_id: uuid.UUID, actor: CurrentActor, db: DbSession, clock: AppClock, settings: AppSettings
) -> JSONResponse:
    lineage = replies.views(db, actor.organization_id, [message_id], content.keyring(settings), clock.now())
    return JSONResponse({"items": lineage.get(message_id, []), "mode": settings.reply_proposals}, headers=PRIVATE)


@router.post("/messages/{message_id}/reply-proposals/{proposal_id}/reject", status_code=201)
@allow_roles(Role.OWNER, Role.OPERATOR)
def reject_reply(
    message_id: uuid.UUID, proposal_id: uuid.UUID, body: RejectBody, actor: CurrentActor, db: DbSession,
    clock: AppClock,
) -> JSONResponse:  # fmt: skip
    review = replies.reject(db, actor=actor, clock=clock, message_id=message_id, proposal_id=proposal_id,
                            reason=body.reason)  # fmt: skip
    return JSONResponse({"id": str(review.id), "decision": review.decision}, status_code=201, headers=PRIVATE)
