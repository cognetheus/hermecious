"""Contacts, permission evidence, suppressions and eligibility evaluation (P4.3, ADR-022).

- Owners and operators add contacts, record (pending) evidence, revoke and suppress (CSRF).
- Only owners verify or reject evidence; nobody can send `verified=true` or a `last_inbound_at`.
- Observers read masked status only.
- `/channel-eligibility/evaluate` returns a simulation-only reading; it is never a send authorization.
"""

import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic import AfterValidator, AwareDatetime, BaseModel, ConfigDict, Field

from app.api.dependencies import AppClock, AppSettings
from app.auth.dependencies import CurrentActor, allow_roles, authorize_request
from app.auth.models import Role
from app.contacts import models, service
from app.eligibility import fixtures, policy
from app.eligibility import service as eligibility
from app.persistence.db import DbSession

router = APIRouter(prefix="/api/v1", tags=["contacts"], dependencies=[Depends(authorize_request)])
NO_STORE = {"Cache-Control": "no-store"}
Key = Annotated[str, Field(pattern=r"^[A-Za-z0-9._:-]{8,100}$")]
Reason = Annotated[str, Field(min_length=3, max_length=500)]


def _printable(value: str) -> str:
    if any(not ch.isprintable() for ch in value):
        raise ValueError("must be plain printable text")
    return value


Text = Annotated[str, AfterValidator(_printable)]


class _Body(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ContactBody(_Body):
    address: Annotated[Text, Field(min_length=8, max_length=32)]
    role: Literal[models.ROLES]  # type: ignore[valid-type]
    idempotency_key: Key


class PermissionBody(_Body):
    purpose: Literal["marketing", "utility"]
    business_name: Annotated[Text, Field(min_length=2, max_length=120)]
    capture_method: Literal[models.CAPTURE_METHODS]  # type: ignore[valid-type]
    consent_wording_version: Annotated[str, Field(pattern=r"^[A-Za-z0-9-]{3,60}$")]
    proof_kind: Literal["form_serial", "web_submission_id", "message_id", "call_recording_id"]
    proof_reference: Annotated[Text, Field(min_length=4, max_length=120)]
    captured_at: AwareDatetime
    idempotency_key: Key


class ReviewBody(_Body):
    decision: Literal["verified", "rejected"]
    reason: Annotated[Text, Field(min_length=3, max_length=500)]
    expected_version: Annotated[int, Field(ge=1)]
    idempotency_key: Key


class RevokeBody(_Body):
    reason: Annotated[Text, Field(min_length=3, max_length=500)]
    expected_version: Annotated[int, Field(ge=1)]
    idempotency_key: Key


class SuppressBody(_Body):
    reason: Literal[models.SUPPRESSION_REASONS]  # type: ignore[valid-type]
    idempotency_key: Key


class EvaluateBody(_Body):
    contact_id: uuid.UUID
    channel: Literal["whatsapp"] = "whatsapp"
    purpose: Literal["marketing", "utility", "service_reply"]
    campaign_id: uuid.UUID | None = None
    template_ref: Annotated[str, Field(pattern=r"^[A-Za-z0-9_.:-]{3,80}$")] | None = None
    inbound_ref: Annotated[str, Field(pattern=r"^fx_[a-z0-9_]{3,80}$")] | None = None


def _respond(created: bool, body: dict[str, object]) -> JSONResponse:
    return JSONResponse(body | {"replayed": not created}, status_code=201 if created else 200, headers=NO_STORE)


@router.post("/accounts/{account_id}/contacts")
@allow_roles(Role.OWNER, Role.OPERATOR)
def create_contact(
    account_id: uuid.UUID, body: ContactBody, actor: CurrentActor, db: DbSession, clock: AppClock, settings: AppSettings
) -> JSONResponse:
    outcome, created = service.create_contact(
        db,
        actor=actor,
        clock=clock,
        keys=service.keyring(settings),
        account_id=account_id,
        address=body.address,
        role=body.role,
        idempotency_key=body.idempotency_key,
    )
    contact = service.get(db, actor.organization_id, uuid.UUID(str(outcome["contact_id"])))
    return _respond(created, service.view(db, contact, full=True))


@router.get("/accounts/{account_id}/contacts")
def list_contacts(account_id: uuid.UUID, actor: CurrentActor, db: DbSession) -> JSONResponse:
    full = actor.role != Role.OBSERVER
    items = [service.view(db, c, full=full) for c in service.list_for_account(db, actor.organization_id, account_id)]
    return JSONResponse({"items": items, "notice": eligibility.NOTICE}, headers=NO_STORE)


@router.get("/contacts/{contact_id}")
def get_contact(contact_id: uuid.UUID, actor: CurrentActor, db: DbSession) -> JSONResponse:
    contact = service.get(db, actor.organization_id, contact_id)
    return JSONResponse(service.view(db, contact, full=actor.role != Role.OBSERVER), headers=NO_STORE)


@router.get("/contacts/{contact_id}/permissions")
def list_permissions(contact_id: uuid.UUID, actor: CurrentActor, db: DbSession) -> JSONResponse:
    contact = service.get(db, actor.organization_id, contact_id)
    view = service.view(db, contact, full=actor.role != Role.OBSERVER)
    return JSONResponse({"items": view["permissions"], "suppressed": view["suppressed"]}, headers=NO_STORE)


@router.post("/contacts/{contact_id}/permissions")
@allow_roles(Role.OWNER, Role.OPERATOR)
def record_permission(
    contact_id: uuid.UUID,
    body: PermissionBody,
    actor: CurrentActor,
    db: DbSession,
    clock: AppClock,
    settings: AppSettings,
) -> JSONResponse:
    outcome, created = service.record_permission(
        db,
        actor=actor,
        clock=clock,
        keys=service.keyring(settings),
        contact_id=contact_id,
        purpose=body.purpose,
        business_name=body.business_name,
        capture_method=body.capture_method,
        consent_wording_version=body.consent_wording_version,
        proof_kind=body.proof_kind,
        proof_reference=body.proof_reference,
        captured_at=body.captured_at,
        idempotency_key=body.idempotency_key,
    )
    return _respond(created, outcome)


@router.post("/contacts/{contact_id}/permissions/{permission_id}/verify")
def review_permission(
    contact_id: uuid.UUID,
    permission_id: uuid.UUID,
    body: ReviewBody,
    actor: CurrentActor,
    db: DbSession,
    clock: AppClock,
) -> JSONResponse:
    """Owner-only (the default for unsafe methods): `verified` or `rejected`."""
    outcome, created = service.review_permission(
        db,
        actor=actor,
        clock=clock,
        contact_id=contact_id,
        permission_id=permission_id,
        decision=body.decision,
        reason=body.reason,
        expected_version=body.expected_version,
        idempotency_key=body.idempotency_key,
    )
    return _respond(created, outcome)


@router.post("/contacts/{contact_id}/permissions/{permission_id}/revoke")
@allow_roles(Role.OWNER, Role.OPERATOR)
def revoke_permission(
    contact_id: uuid.UUID,
    permission_id: uuid.UUID,
    body: RevokeBody,
    actor: CurrentActor,
    db: DbSession,
    clock: AppClock,
) -> JSONResponse:
    outcome, created = service.revoke_permission(
        db,
        actor=actor,
        clock=clock,
        contact_id=contact_id,
        permission_id=permission_id,
        reason=body.reason,
        expected_version=body.expected_version,
        idempotency_key=body.idempotency_key,
    )
    return _respond(created, outcome)


@router.post("/contacts/{contact_id}/suppress")
@allow_roles(Role.OWNER, Role.OPERATOR)
def suppress(
    contact_id: uuid.UUID, body: SuppressBody, actor: CurrentActor, db: DbSession, clock: AppClock
) -> JSONResponse:
    outcome, created = service.suppress(
        db, actor=actor, clock=clock, contact_id=contact_id, reason=body.reason, idempotency_key=body.idempotency_key
    )
    return _respond(created, outcome)


@router.post("/channel-eligibility/evaluate")
@allow_roles(Role.OWNER, Role.OPERATOR)
def evaluate(
    body: EvaluateBody, actor: CurrentActor, db: DbSession, clock: AppClock, settings: AppSettings
) -> JSONResponse:
    result = eligibility.evaluate(
        db,
        actor=actor,
        clock=clock,
        settings=settings,
        contact_id=body.contact_id,
        purpose=body.purpose,
        campaign_id=body.campaign_id,
        template_ref=body.template_ref,
        inbound_ref=body.inbound_ref,
    )
    return JSONResponse(result, headers=NO_STORE)


@router.get("/channel-eligibility/policy")
def policy_info(settings: AppSettings) -> JSONResponse:
    catalogue = fixtures.catalogue() if settings.environment != "production" else {"templates": [], "inbound": []}
    return JSONResponse(
        {
            "policy_version": policy.POLICY_VERSION,
            "business_name": policy.BUSINESS_NAME,
            "consent_wording": policy.CONSENT_WORDING,
            "notice": eligibility.NOTICE,
            "fixtures": catalogue,
            "live_send_authorized": False,
        },
        headers=NO_STORE,
    )
