"""Conversation ownership and handoff API (P6.3, ADR-033). Human commands only; nothing here can send.

Owners and operators read and command (CSRF on writes); observers read the ownership state and the queue only
(masked: no message content). `block` and `reopen` are owner-only.
"""

import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from app.api.dependencies import AppClock
from app.auth.dependencies import CurrentActor, allow_roles, authorize_request
from app.auth.models import Role
from app.conversations import service
from app.core.request_context import current_request_id
from app.persistence.db import DbSession

router = APIRouter(prefix="/api/v1/inbox/whatsapp", tags=["conversations"], dependencies=[Depends(authorize_request)])
PRIVATE = {"Cache-Control": "private, no-store"}


class CommandBody(BaseModel):
    model_config = ConfigDict(extra="forbid")  # a model-generated "tool call", owner_generation or user list is refused
    command: Literal["takeover", "assign", "pause", "block", "resolve", "release_to_agent", "reopen", "open_handoff",
                     "acknowledge_handoff"]  # fmt: skip
    expected_revision: Annotated[int, Field(ge=1)]
    reason: Literal["human_requested", "unknown_offer", "sensitive", "conflicting_facts", "operator_takeover",
                    "manual", "unmatched_contact", "quality_concern", "resolved_by_operator",
                    "agent_release_approved"]  # fmt: skip
    idempotency_key: Annotated[str, Field(pattern=r"^[A-Za-z0-9._:-]{8,100}$")]
    note: Annotated[str, Field(max_length=300)] = ""
    assignee_id: uuid.UUID | None = None
    urgency: Literal["normal", "high"] = "normal"


@router.get("/threads/{thread_id}/ownership")
def ownership(thread_id: uuid.UUID, actor: CurrentActor, db: DbSession, clock: AppClock) -> JSONResponse:
    service._thread(db, actor.organization_id, thread_id)
    service.ensure(db, actor.organization_id, thread_id, clock.now())
    db.commit()
    return JSONResponse(service.view(db, actor.organization_id, thread_id), headers=PRIVATE)


@router.post("/threads/{thread_id}/ownership")
@allow_roles(Role.OWNER, Role.OPERATOR)
def command(
    thread_id: uuid.UUID, body: CommandBody, actor: CurrentActor, db: DbSession, clock: AppClock
) -> JSONResponse:
    state, applied = service.command(
        db, actor=actor, clock=clock, thread_id=thread_id, name=body.command,
        expected_revision=body.expected_revision, reason=body.reason, idempotency_key=body.idempotency_key,
        note=body.note, assignee_id=body.assignee_id, urgency=body.urgency, correlation_id=current_request_id(),
    )  # fmt: skip
    return JSONResponse(state | {"applied": applied}, headers=PRIVATE)


@router.get("/handoffs")
def handoffs(actor: CurrentActor, db: DbSession) -> JSONResponse:
    return JSONResponse({"items": service.handoff_queue(db, actor.organization_id)}, headers=PRIVATE)


@router.get("/assignees")
@allow_roles(Role.OWNER, Role.OPERATOR)
def assignees(actor: CurrentActor, db: DbSession) -> JSONResponse:
    return JSONResponse({"items": service.assignees(db, actor.organization_id)}, headers=PRIVATE)
