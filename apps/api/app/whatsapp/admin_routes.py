"""WhatsApp integration admin API (P5.3, ADR-028). Session, CSRF and roles as everywhere else.

- Any role reads the connection status, catalog, recipients (masked) and test sends (observers get status only).
- Owners bind the connection, sync templates, register or revoke test recipients, confirm a test send and mark
  a stale reservation indeterminate.
- Owners and operators create (non-sending) previews and cancel them.

There is no route that sends to an account, contact, campaign or any number from a request.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from app.api.dependencies import AppClock, AppSettings
from app.auth.dependencies import CurrentActor, allow_roles, authorize_request
from app.auth.models import Role
from app.persistence.db import DbSession
from app.whatsapp import service as connections
from app.whatsapp import test_sends

router = APIRouter(prefix="/api/v1/integrations/whatsapp", tags=["whatsapp"], dependencies=[Depends(authorize_request)])
NO_STORE = {"Cache-Control": "no-store"}
Key = Annotated[str, Field(pattern=r"^[A-Za-z0-9._:-]{8,100}$")]


class _Body(BaseModel):
    model_config = ConfigDict(extra="forbid")  # phone_number, body, campaign_id, account_id, ... are refused


class RecipientBody(_Body):
    address: Annotated[str, Field(min_length=8, max_length=32)]
    label: Annotated[str, Field(min_length=2, max_length=80)]
    consent_statement: Annotated[str, Field(min_length=20, max_length=500)]


class PreviewBody(_Body):
    recipient_id: uuid.UUID
    template_id: uuid.UUID  # the catalog row id
    parameters: Annotated[list[Annotated[str, Field(min_length=1, max_length=200)]], Field(max_length=10)] = []
    idempotency_key: Key


class ConfirmBody(_Body):
    preview_digest: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
    confirmation_nonce: Annotated[str, Field(min_length=20, max_length=100)]


@router.get("/connection")
def connection(actor: CurrentActor, db: DbSession, settings: AppSettings) -> JSONResponse:
    return JSONResponse(test_sends.connection_status(db, actor.organization_id, settings), headers=NO_STORE)


@router.post("/connection/bind")
def bind(actor: CurrentActor, db: DbSession, clock: AppClock, settings: AppSettings) -> JSONResponse:
    bound = connections.bind_connection(db, actor=actor, clock=clock, settings=settings)
    return JSONResponse({"connection_id": str(bound.connection_id), "mode": bound.mode}, headers=NO_STORE)


@router.get("/templates")
def templates(actor: CurrentActor, db: DbSession, clock: AppClock) -> JSONResponse:
    items = test_sends.templates_view(db, actor.organization_id, clock.now())
    return JSONResponse({"items": items, "source": "meta"}, headers=NO_STORE)


@router.post("/templates/sync")
def sync(actor: CurrentActor, db: DbSession, clock: AppClock, settings: AppSettings) -> JSONResponse:
    result = test_sends.sync_templates(db, actor=actor, clock=clock, settings=settings)
    return JSONResponse(result, headers=NO_STORE)


@router.get("/test-recipients")
def recipients(actor: CurrentActor, db: DbSession) -> JSONResponse:
    items = test_sends.recipients_view(db, actor.organization_id, full=actor.role != Role.OBSERVER)
    return JSONResponse({"items": items}, headers=NO_STORE)


@router.post("/test-recipients", status_code=201)
def register(
    body: RecipientBody, actor: CurrentActor, db: DbSession, clock: AppClock, settings: AppSettings
) -> JSONResponse:
    row = test_sends.register_recipient(
        db, actor=actor, clock=clock, settings=settings, address=body.address, label=body.label,
        consent_statement=body.consent_statement,
    )  # fmt: skip
    return JSONResponse(
        {"id": str(row.id), "label": row.label, "address": row.address_hint, "status": row.status},
        status_code=201,
        headers=NO_STORE,
    )


@router.post("/test-recipients/{recipient_id}/revoke")
def revoke(recipient_id: uuid.UUID, actor: CurrentActor, db: DbSession, clock: AppClock) -> JSONResponse:
    row = test_sends.revoke_recipient(db, actor=actor, clock=clock, recipient_id=recipient_id)
    return JSONResponse({"id": str(row.id), "status": row.status}, headers=NO_STORE)


@router.get("/test-sends")
def list_sends(actor: CurrentActor, db: DbSession) -> JSONResponse:
    full = actor.role != Role.OBSERVER
    items = [test_sends.view(db, r, full=full) for r in test_sends.list_sends(db, actor.organization_id)]
    return JSONResponse({"items": items}, headers=NO_STORE)


@router.post("/test-sends", status_code=201)
@allow_roles(Role.OWNER, Role.OPERATOR)
def create_preview(
    body: PreviewBody, actor: CurrentActor, db: DbSession, clock: AppClock, settings: AppSettings
) -> JSONResponse:
    row, nonce = test_sends.preview(
        db, actor=actor, clock=clock, settings=settings, recipient_id=body.recipient_id,
        template_row_id=body.template_id, parameters=body.parameters, idempotency_key=body.idempotency_key,
    )  # fmt: skip
    payload = test_sends.view(db, row, full=True) | {"confirmation_nonce": nonce, "replayed": nonce is None}
    return JSONResponse(payload, status_code=201 if nonce else 200, headers=NO_STORE)


@router.get("/test-sends/{send_id}")
def get_send(send_id: uuid.UUID, actor: CurrentActor, db: DbSession) -> JSONResponse:
    row = test_sends.get(db, actor.organization_id, send_id)
    return JSONResponse(test_sends.view(db, row, full=actor.role != Role.OBSERVER), headers=NO_STORE)


@router.post("/test-sends/{send_id}/confirm")
def confirm(
    send_id: uuid.UUID, body: ConfirmBody, actor: CurrentActor, db: DbSession, clock: AppClock, settings: AppSettings
) -> JSONResponse:
    """Owner only (the default for unsafe methods). Sends one REAL message to the registered test number."""
    row, sent = test_sends.confirm(
        db, actor=actor, clock=clock, settings=settings, send_id=send_id, preview_digest=body.preview_digest,
        nonce=body.confirmation_nonce,
    )  # fmt: skip
    return JSONResponse(test_sends.view(db, row, full=True) | {"replayed": not sent}, headers=NO_STORE)


@router.post("/test-sends/{send_id}/cancel")
@allow_roles(Role.OWNER, Role.OPERATOR)
def cancel(send_id: uuid.UUID, actor: CurrentActor, db: DbSession, clock: AppClock) -> JSONResponse:
    row = test_sends.cancel(db, actor=actor, clock=clock, send_id=send_id)
    return JSONResponse(test_sends.view(db, row, full=True), headers=NO_STORE)


@router.post("/test-sends/{send_id}/mark-indeterminate")
def mark_indeterminate(send_id: uuid.UUID, actor: CurrentActor, db: DbSession, clock: AppClock) -> JSONResponse:
    row = test_sends.mark_indeterminate(db, actor=actor, clock=clock, send_id=send_id)
    return JSONResponse(test_sends.view(db, row, full=True), headers=NO_STORE)
