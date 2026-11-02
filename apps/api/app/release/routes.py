"""WhatsApp production readiness and the operator-only pilot gate (P5.5, ADR-030).

- Owners and operators read readiness, attestations, authorizations and pilot sends; observers get 403.
- Owners evaluate readiness, record attestations, sync the production catalog (read-only), authorize, pause,
  resume or revoke a pilot, confirm a pilot send and mark a stale reservation indeterminate.
- Owners and operators create (non-sending) pilot previews and cancel them.

No route takes an arbitrary recipient, a template status, a campaign or a skip flag. Nothing here can enable the
deploy-time live gate.
"""

import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from app.api.dependencies import AppClock, AppSettings
from app.auth.dependencies import CurrentActor, allow_roles, authorize_request
from app.auth.models import Role
from app.core.settings import Settings
from app.persistence.db import DbSession
from app.release import pilot, service

router = APIRouter(prefix="/api/v1/release/whatsapp", tags=["release"], dependencies=[Depends(authorize_request)])
PRIVATE = {"Cache-Control": "private, no-store"}
Key = Annotated[str, Field(pattern=r"^[A-Za-z0-9._:-]{8,100}$")]


class _Body(BaseModel):
    model_config = ConfigDict(extra="forbid")  # phone_number, template_status, skip_consent, ... are refused


class AttestBody(_Body):
    kind: Literal["meta_business_verification", "pakistan_legal_review", "real_test_receipt", "operations_readiness"]
    statement: Annotated[str, Field(min_length=20, max_length=1000)]
    evidence_ref: Annotated[str, Field(min_length=10, max_length=500)]


class AuthorizeBody(_Body):
    assessment_id: uuid.UUID
    acknowledgement: Annotated[str, Field(max_length=200)]
    purpose: Literal["marketing", "utility"]
    max_per_day: Annotated[int, Field(ge=1, le=3)] = 3
    days: Annotated[int, Field(ge=1, le=14)] = 7


class PauseBody(_Body):
    reason: Literal["human_takeover", "quality_alert", "investigation", "opt_out_review"]


class PreviewBody(_Body):
    draft_id: uuid.UUID
    parameters: Annotated[list[Annotated[str, Field(min_length=1, max_length=200)]], Field(max_length=10)] = []
    idempotency_key: Key


class ConfirmBody(_Body):
    preview_digest: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
    confirmation_nonce: Annotated[str, Field(min_length=20, max_length=100)]
    recipient_number: Annotated[str, Field(min_length=8, max_length=32)]


@router.get("/readiness")
@allow_roles(Role.OWNER, Role.OPERATOR)
def readiness(actor: CurrentActor, db: DbSession, clock: AppClock, settings: AppSettings) -> JSONResponse:
    now, org = clock.now(), actor.organization_id
    row = service.latest(db, org)
    payload = {
        "assessment": service.assessment_view(row, now) if row else None,
        "attestations": service.attestations_view(db, org, now),
        "authorizations": [service.authorization_view(a, now) for a in service.authorizations(db, org)],
        "live_gate": service.live_gate(settings) or "open",
        "banner": service.BANNER, "acknowledgement": service.PILOT_ACK, "pilot_label": pilot.CONFIRM_LABEL,
    }  # fmt: skip
    return JSONResponse(payload, headers=PRIVATE)


@router.post("/readiness/evaluate", status_code=201)
def evaluate(actor: CurrentActor, db: DbSession, clock: AppClock, settings: AppSettings) -> JSONResponse:
    row = service.evaluate(db, actor=actor, clock=clock, settings=settings)
    return JSONResponse(service.assessment_view(row, clock.now()), status_code=201, headers=PRIVATE)


@router.post("/attestations", status_code=201)
def attest(body: AttestBody, actor: CurrentActor, db: DbSession, clock: AppClock) -> JSONResponse:
    row = service.attest(db, actor=actor, clock=clock, kind=body.kind, statement=body.statement,
                         evidence_ref=body.evidence_ref)  # fmt: skip
    return JSONResponse({"id": str(row.id), "kind": row.kind}, status_code=201, headers=PRIVATE)


@router.post("/catalog/sync")
def sync(actor: CurrentActor, db: DbSession, clock: AppClock, settings: AppSettings) -> JSONResponse:
    return JSONResponse(service.sync_production_catalog(db, actor=actor, clock=clock, settings=settings),
                        headers=PRIVATE)  # fmt: skip


@router.post("/pilot", status_code=201)
def authorize(
    body: AuthorizeBody, actor: CurrentActor, db: DbSession, clock: AppClock, settings: AppSettings
) -> JSONResponse:
    row = service.authorize(
        db, actor=actor, clock=clock, settings=settings, assessment_id=body.assessment_id,
        acknowledgement=body.acknowledgement, purpose=body.purpose, max_per_day=body.max_per_day, days=body.days,
    )  # fmt: skip
    return JSONResponse(service.authorization_view(row, clock.now()), status_code=201, headers=PRIVATE)


@router.post("/pilot/{auth_id}/pause")
def pause(auth_id: uuid.UUID, body: PauseBody, actor: CurrentActor, db: DbSession, clock: AppClock) -> JSONResponse:
    row = service.set_status(db, actor=actor, clock=clock, auth_id=auth_id, action="pause", reason=body.reason)
    return JSONResponse(service.authorization_view(row, clock.now()), headers=PRIVATE)


@router.post("/pilot/{auth_id}/resume")
def resume(auth_id: uuid.UUID, actor: CurrentActor, db: DbSession, clock: AppClock) -> JSONResponse:
    row = service.set_status(db, actor=actor, clock=clock, auth_id=auth_id, action="resume")
    return JSONResponse(service.authorization_view(row, clock.now()), headers=PRIVATE)


@router.post("/pilot/{auth_id}/revoke")
def revoke(auth_id: uuid.UUID, actor: CurrentActor, db: DbSession, clock: AppClock) -> JSONResponse:
    row = service.set_status(db, actor=actor, clock=clock, auth_id=auth_id, action="revoke")
    return JSONResponse(service.authorization_view(row, clock.now()), headers=PRIVATE)


@router.post("/pilot-sends", status_code=201)
@allow_roles(Role.OWNER, Role.OPERATOR)
def create_preview(
    body: PreviewBody, actor: CurrentActor, db: DbSession, clock: AppClock, settings: AppSettings
) -> JSONResponse:
    row, nonce = pilot.preview(db, actor=actor, clock=clock, settings=settings, draft_id=body.draft_id,
                               parameters=body.parameters, idempotency_key=body.idempotency_key)  # fmt: skip
    payload = pilot.view(db, row) | {"confirmation_nonce": nonce, "replayed": nonce is None}
    return JSONResponse(payload, status_code=201 if nonce else 200, headers=PRIVATE)


@router.get("/pilot-sends/{send_id}")
@allow_roles(Role.OWNER, Role.OPERATOR)
def get_send(send_id: uuid.UUID, actor: CurrentActor, db: DbSession) -> JSONResponse:
    return JSONResponse(pilot.view(db, pilot.get(db, actor.organization_id, send_id)), headers=PRIVATE)


@router.post("/pilot-sends/{send_id}/confirm")
def confirm(
    send_id: uuid.UUID, body: ConfirmBody, request: Request, actor: CurrentActor, db: DbSession, clock: AppClock
) -> JSONResponse:
    """Owner only. The deploy-time live gate, the pilot authorization and every per-send check must all hold."""

    def current() -> Settings:
        settings: Settings = request.app.state.settings
        return settings

    row, sent = pilot.confirm(
        db, actor=actor, clock=clock, settings=current, send_id=send_id, preview_digest=body.preview_digest,
        nonce=body.confirmation_nonce, recipient_number=body.recipient_number,
    )  # fmt: skip
    return JSONResponse(pilot.view(db, row) | {"replayed": not sent}, headers=PRIVATE)


@router.post("/pilot-sends/{send_id}/cancel")
@allow_roles(Role.OWNER, Role.OPERATOR)
def cancel(send_id: uuid.UUID, actor: CurrentActor, db: DbSession, clock: AppClock) -> JSONResponse:
    return JSONResponse(pilot.view(db, pilot.cancel(db, actor=actor, clock=clock, send_id=send_id)), headers=PRIVATE)


@router.post("/pilot-sends/{send_id}/mark-indeterminate")
def mark_indeterminate(send_id: uuid.UUID, actor: CurrentActor, db: DbSession, clock: AppClock) -> JSONResponse:
    row = pilot.mark_indeterminate(db, actor=actor, clock=clock, send_id=send_id)
    return JSONResponse(pilot.view(db, row), headers=PRIVATE)
