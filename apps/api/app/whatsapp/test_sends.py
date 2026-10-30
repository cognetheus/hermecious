"""Provider-authoritative templates and the single guarded operator test send (P5.3, ADR-028).

This is the only caller of `MetaCloudTransport.send_template` in the application. It sends **one** approved
template to **one** registered, operator-owned test number, after an owner confirms an exact preview. It is never
reachable from campaigns, drafts, accounts, contacts or jobs.

**Flow:**
1. `preview`: a non-sending record with an exact preview digest, a one-time nonce (shown once) and a 10-minute
   expiry.
2. `confirm` (owner, CSRF):
   - checks the digest and nonce;
   - re-checks every condition fresh: mode, test kill switch, the live-outbound refusal, the binding, the
     recipient (active, still allowlisted, not suppressed, not a sourced contact), the daily cap, and that no
     send is in flight;
   - re-fetches the template from Meta (APPROVED, same components);
   - **reserves** (commit), then makes exactly one Graph call, then records `provider_accepted`,
     `definitively_rejected` or `indeterminate`.
3. Nothing is ever resent automatically. A stale reservation can only be marked `indeterminate` by an owner.

`sent`, `delivered` and `read` come only from signed webhooks (P5.2), joined by `(connection, wamid)` on read.
"""

import hashlib
import json
import secrets
import uuid
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any

from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.accounts import management
from app.accounts import service as account_service
from app.auth.dependencies import Capability
from app.auth.service import Actor
from app.contacts import addresses
from app.contacts import service as contacts
from app.contacts.models import Contact, SuppressionEntry
from app.core.clock import BUSINESS_TZ, Clock
from app.core.errors import Conflict, DependencyUnavailable, Forbidden, NotFound, Unprocessable
from app.core.settings import Settings
from app.whatsapp import service as connections
from app.whatsapp import transport as wa
from app.whatsapp.config import test_recipient_numbers
from app.whatsapp.contracts import (
    OutboundKind,
    ProviderConnectionView,
    ResolvedRecipient,
    SendIntent,
    TemplateComponent,
    TemplateParameter,
)
from app.whatsapp.models import (
    ProviderConnection,
    ProviderMessageStatus,
    ProviderStatusObservation,
    ProviderTemplate,
    ProviderTestRecipient,
    ProviderTestSend,
)

POLICY_REVISION = "whatsapp-test-send-1.0"
CONFIRM_LABEL = "This will send a REAL WhatsApp message to my registered test number."
PREVIEW_TTL = timedelta(minutes=10)
TEMPLATE_FRESHNESS = timedelta(minutes=15)
STALE_RESERVATION = timedelta(minutes=2)
DAILY_CAP = 3  # confirmed attempts per organization per Asia/Karachi day (internal safety default)
ATTEMPTED = ("reserved", "provider_accepted", "definitively_rejected", "indeterminate")
STATE_OF = {
    "accepted": "provider_accepted",
    "definitive_rejected": "definitively_rejected",
    "indeterminate": "indeterminate",
}
# Contract tests inject a local fake Graph layer here; it is consulted only in `contract_test` mode.
CONTRACT_HTTP: Callable[[ProviderConnectionView], wa.GraphHttp] | None = None


def _digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()


def _require_test_mode(settings: Settings) -> None:
    if settings.whatsapp_mode not in ("contract_test", "provider_test") or settings.live_outbound_enabled:
        raise Conflict("test sending is available only in provider_test mode (contract_test for automated tests)")


def _transport(
    settings: Settings, connection: ProviderConnectionView, now: Callable[[], datetime]
) -> wa.MetaCloudTransport:
    http = CONTRACT_HTTP(connection) if settings.whatsapp_mode == "contract_test" and CONTRACT_HTTP else None
    return wa.build_transport(settings, connection, now, http=http)


def _provider_error(exc: wa.ProviderCallError) -> Exception:
    if exc.error_class in ("provider_transient", "provider_quota", "provider_uncertain"):
        return DependencyUnavailable(f"WhatsApp provider unavailable ({exc.error_class})")
    return Conflict(f"WhatsApp provider refused the request ({exc.error_class})")


# --- template catalog --------------------------------------------------------------------------------------------


def sync_templates(db: Session, *, actor: Actor, clock: Clock, settings: Settings) -> dict[str, Any]:
    """Owner-only read of Meta's catalog. Provider strings are stored exactly; missing ones become NOT_RETURNED."""
    account_service._require(actor, Capability.ADMINISTER)
    _require_test_mode(settings)
    connection = connections.connection_for(db, actor.organization_id, settings)
    try:
        fetched = _transport(settings, connection, clock.now).list_templates()
    except wa.ProviderCallError as exc:
        raise _provider_error(exc) from None
    now = clock.now()
    seen = set()
    for t in fetched:
        seen.add(t.template_id)
        values = {
            "name": t.name, "language": t.language, "category": t.category, "provider_status": t.provider_status,
            "components_digest": t.components_digest, "body_text": t.body_text,
            "body_parameter_count": t.body_parameter_count, "header_parameter_count": t.header_parameter_count,
            "supported": t.supported, "fetched_at": now,
        }  # fmt: skip
        db.execute(
            insert(ProviderTemplate)
            .values(id=uuid.uuid4(), organization_id=actor.organization_id,
                    provider_connection_id=connection.connection_id, template_id=t.template_id, **values)
            .on_conflict_do_update(constraint="uq_provider_templates_template", set_=values)
        )  # fmt: skip
    for row in db.scalars(
        select(ProviderTemplate).where(ProviderTemplate.provider_connection_id == connection.connection_id)
    ):
        if row.template_id not in seen:
            row.provider_status, row.fetched_at = "NOT_RETURNED", now  # never kept as approved by default
    management._audit(db, actor, clock, "whatsapp.templates_synced", connection.connection_id,
                      {"templates": len(fetched)}, target_type="provider_connection")  # fmt: skip
    db.commit()
    return {"templates": len(fetched)}


def _template_view(row: ProviderTemplate, now: datetime) -> dict[str, Any]:
    fresh = now - row.fetched_at <= TEMPLATE_FRESHNESS
    return {
        "id": str(row.id), "template_id": row.template_id, "name": row.name, "language": row.language,
        "category": row.category, "provider_status": row.provider_status, "supported": row.supported,
        "body_text": row.body_text, "body_parameter_count": row.body_parameter_count,
        "header_parameter_count": row.header_parameter_count, "fetched_at": row.fetched_at.isoformat(),
        "fresh": fresh,
        "usable_for_test": bool(fresh and row.supported and row.provider_status == "APPROVED"
                                and row.category in wa.CATEGORIES["operator_test"] and row.header_parameter_count == 0),
    }  # fmt: skip


def templates_view(db: Session, org: uuid.UUID, now: datetime) -> list[dict[str, Any]]:
    rows = db.scalars(
        select(ProviderTemplate).where(ProviderTemplate.organization_id == org).order_by(ProviderTemplate.name)
    )
    return [_template_view(r, now) for r in rows]


# --- test recipients ---------------------------------------------------------------------------------------------


def _allowlisted(settings: Settings, keys: addresses.Keyring, key_id: str, digest: str) -> str | None:
    """The allowlisted number whose digest matches, or None (the number is never read from a request)."""
    key = dict(keys.keys).get(key_id)
    if key is None:
        return None
    for number in test_recipient_numbers(settings) or ():
        if addresses.digest(key, number) == digest:
            return number
    return None


def _sourced_contact(db: Session, org: uuid.UUID, keys: addresses.Keyring, e164: str) -> bool:
    every = addresses.digests(keys, e164)
    return (
        db.scalar(
            select(Contact.id).where(
                Contact.organization_id == org,
                func.concat(Contact.key_id, ":", Contact.address_digest).in_([f"{k}:{d}" for k, d in every.items()]),
            )
        )
        is not None
    )


def _suppressed(db: Session, org: uuid.UUID, keys: addresses.Keyring, e164: str) -> bool:
    every = addresses.digests(keys, e164)
    return (
        db.scalar(
            select(SuppressionEntry.id).where(
                SuppressionEntry.organization_id == org,
                func.concat(SuppressionEntry.key_id, ":", SuppressionEntry.address_digest).in_(
                    [f"{k}:{d}" for k, d in every.items()]
                ),
            )
        )
        is not None
    )


def register_recipient(
    db: Session, *, actor: Actor, clock: Clock, settings: Settings, address: str, label: str, consent_statement: str
) -> ProviderTestRecipient:
    """Owner-only. The number must already be in the server-side allowlist and must not be any sourced contact."""
    account_service._require(actor, Capability.ADMINISTER)
    _require_test_mode(settings)
    org = actor.organization_id
    connection = connections.connection_for(db, org, settings)
    keys = contacts.keyring(settings)
    try:
        e164 = addresses.canonical(address)
    except addresses.AddressError:
        raise Unprocessable("INVALID_ADDRESS: not a valid international phone number") from None
    if e164 not in (test_recipient_numbers(settings) or ()):
        raise Unprocessable("NOT_ALLOWLISTED: add the number to HERMECIOUS_WHATSAPP_TEST_RECIPIENTS on the server")
    if _sourced_contact(db, org, keys, e164):
        raise Conflict("this number belongs to a sourced contact; test recipients must be operator-owned numbers")
    if _suppressed(db, org, keys, e164):
        raise Conflict("this number is suppressed")
    key_id, key = keys.current
    digest = addresses.digest(key, e164)
    existing = db.scalar(
        select(ProviderTestRecipient).where(
            ProviderTestRecipient.provider_connection_id == connection.connection_id,
            ProviderTestRecipient.key_id == key_id,
            ProviderTestRecipient.address_digest == digest,
        )
    )
    now = clock.now()
    if existing is not None:
        if existing.status == "revoked":
            raise Conflict("this test recipient was revoked; it is not reactivated automatically")
        return existing
    row = ProviderTestRecipient(
        organization_id=org, provider_connection_id=connection.connection_id, label=" ".join(label.split())[:80],
        key_id=key_id, address_digest=digest, address_hint=addresses.mask(e164),
        consent_statement=" ".join(consent_statement.split()), consented_by=actor.user_id, consented_at=now,
        status="active", version=1,
    )  # fmt: skip
    db.add(row)
    db.flush()
    management._audit(db, actor, clock, "whatsapp.test_recipient_registered", row.id,
                      {"label": row.label, "address": row.address_hint},
                      target_type="provider_test_recipient")  # fmt: skip
    db.commit()
    return row


def revoke_recipient(db: Session, *, actor: Actor, clock: Clock, recipient_id: uuid.UUID) -> ProviderTestRecipient:
    account_service._require(actor, Capability.ADMINISTER)
    row = db.scalar(
        select(ProviderTestRecipient)
        .where(ProviderTestRecipient.organization_id == actor.organization_id, ProviderTestRecipient.id == recipient_id)
        .with_for_update()
    )
    if row is None:
        raise NotFound()
    if row.status == "active":
        row.status, row.revoked_at, row.version = "revoked", clock.now(), row.version + 1
        management._audit(db, actor, clock, "whatsapp.test_recipient_revoked", row.id, {},
                          target_type="provider_test_recipient")  # fmt: skip
    db.commit()
    return row


def recipients_view(db: Session, org: uuid.UUID, *, full: bool) -> list[dict[str, Any]]:
    rows = db.scalars(
        select(ProviderTestRecipient)
        .where(ProviderTestRecipient.organization_id == org)
        .order_by(ProviderTestRecipient.consented_at)
    )
    out = []
    for r in rows:
        item: dict[str, Any] = {"id": str(r.id), "label": r.label, "address": r.address_hint, "status": r.status}
        if full:
            item |= {"consent_statement": r.consent_statement, "consented_at": r.consented_at.isoformat()}
        out.append(item)
    return out


# --- preview -----------------------------------------------------------------------------------------------------


def _usable_template(db: Session, org: uuid.UUID, template_row_id: uuid.UUID, now: datetime) -> ProviderTemplate:
    row = db.scalar(
        select(ProviderTemplate).where(ProviderTemplate.organization_id == org, ProviderTemplate.id == template_row_id)
    )
    if row is None:
        raise NotFound()
    view = _template_view(row, now)
    if not view["usable_for_test"]:
        reason = (
            "stale_catalog" if not view["fresh"] else
            "not_approved" if row.provider_status != "APPROVED" else
            "unsupported_components" if not row.supported or row.header_parameter_count else "category_not_allowed"
        )  # fmt: skip
        raise Conflict(f"template not usable for a test send: {reason}")
    return row


def _render(body: str | None, params: list[str]) -> str | None:
    if body is None:
        return None
    rendered = body
    for index, value in enumerate(params, start=1):
        rendered = rendered.replace(f"{{{{{index}}}}}", value)
    return rendered


def preview(
    db: Session,
    *,
    actor: Actor,
    clock: Clock,
    settings: Settings,
    recipient_id: uuid.UUID,
    template_row_id: uuid.UUID,
    parameters: list[str],
    idempotency_key: str,
) -> tuple[ProviderTestSend, str | None]:
    """A non-sending preview. Returns (row, one-time nonce); a replay returns no nonce (start a new preview)."""
    account_service._require(actor, Capability.MUTATE)
    _require_test_mode(settings)
    org = actor.organization_id
    request = _digest(["preview", str(recipient_id), str(template_row_id), parameters])
    prior = db.scalar(
        select(ProviderTestSend).where(
            ProviderTestSend.organization_id == org, ProviderTestSend.idempotency_key == idempotency_key
        )
    )
    if prior is not None:
        if prior.request_digest != request:
            raise Conflict("idempotency_key was already used for a different test send")
        return prior, None
    connection = connections.connection_for(db, org, settings)
    recipient = db.scalar(
        select(ProviderTestRecipient).where(
            ProviderTestRecipient.organization_id == org, ProviderTestRecipient.id == recipient_id
        )
    )
    if recipient is None or recipient.provider_connection_id != connection.connection_id:
        raise NotFound()
    if recipient.status != "active":
        raise Conflict("the test recipient is revoked")
    now = clock.now()
    template = _usable_template(db, org, template_row_id, now)
    try:
        typed = [TemplateParameter(text=p) for p in parameters]
    except ValidationError:
        raise Unprocessable("PARAMETERS_INVALID: plain text only (no links, numbers or control characters)") from None
    if len(typed) != template.body_parameter_count:
        raise Unprocessable("PARAMETERS_INVALID: the count does not match the approved template's placeholders")
    row_version = db.scalar(select(ProviderConnection.version).where(ProviderConnection.id == connection.connection_id))
    preview_digest = _digest({
        "phone_number_id": connection.phone_number_id, "waba_id": connection.waba_id,
        "template_id": template.template_id,
        "name": template.name, "language": template.language, "category": template.category,
        "components_digest": template.components_digest, "parameters": parameters, "recipient": str(recipient.id),
    })  # fmt: skip
    nonce = secrets.token_urlsafe(32)
    row = ProviderTestSend(
        organization_id=org, provider_connection_id=connection.connection_id, connection_version=row_version or 1,
        recipient_id=recipient.id, template_row_id=template.id, template_name=template.name,
        template_language=template.language, template_category=template.category,
        components_digest=template.components_digest, params_json=parameters, preview_digest=preview_digest,
        nonce_digest=hashlib.sha256(nonce.encode()).hexdigest(), expires_at=now + PREVIEW_TTL,
        state="awaiting_confirmation", policy_revision=POLICY_REVISION, requested_by=actor.user_id,
        idempotency_key=idempotency_key, request_digest=request, created_at=now, updated_at=now, version=1,
    )  # fmt: skip
    db.add(row)
    try:
        db.flush()
        management._audit(db, actor, clock, "whatsapp.test_send_previewed", row.id,
                          {"template": template.name, "recipient": recipient.address_hint},
                          target_type="provider_test_send")  # fmt: skip
        db.commit()
    except IntegrityError:
        db.rollback()
        raise Conflict("a concurrent preview used this idempotency key; reload") from None
    return row, nonce


# --- confirm -----------------------------------------------------------------------------------------------------


def _deny(db: Session, row: ProviderTestSend, reason: str, now: datetime) -> Conflict:
    row.state, row.denial_reason, row.updated_at, row.version = "denied", reason, now, row.version + 1
    db.commit()
    return Conflict(f"test send denied: {reason}")


def _lock(db: Session, org: uuid.UUID, send_id: uuid.UUID) -> ProviderTestSend:
    row = db.scalar(
        select(ProviderTestSend)
        .where(ProviderTestSend.organization_id == org, ProviderTestSend.id == send_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if row is None:
        raise NotFound()
    return row


def confirm(
    db: Session,
    *,
    actor: Actor,
    clock: Clock,
    settings: Settings,
    send_id: uuid.UUID,
    preview_digest: str,
    nonce: str,
) -> tuple[ProviderTestSend, bool]:
    """Owner-only. Returns (row, sent_now). Exactly one Graph call per preview, ever."""
    account_service._require(actor, Capability.ADMINISTER)
    org = actor.organization_id
    row = _lock(db, org, send_id)
    nonce_ok = secrets.compare_digest(hashlib.sha256(nonce.encode()).hexdigest(), row.nonce_digest)
    digest_ok = secrets.compare_digest(preview_digest, row.preview_digest)
    if row.state != "awaiting_confirmation":
        db.rollback()
        if nonce_ok and digest_ok:
            return row, False  # the same confirmation, replayed: the recorded outcome stands
        raise Conflict(f"this test send is {row.state}")
    if not (nonce_ok and digest_ok):
        db.rollback()
        raise Conflict("the confirmation does not match the preview you were shown")
    now = clock.now()
    if now >= row.expires_at:
        row.state, row.updated_at, row.version = "expired", now, row.version + 1
        db.commit()
        raise Conflict("the preview expired; create a new one")
    # Fresh checks, in the same transaction as the reservation.
    if settings.whatsapp_mode not in ("contract_test", "provider_test") or settings.live_outbound_enabled:
        raise _deny(db, row, "not_test_mode", now)
    if not settings.whatsapp_test_outbound_enabled:
        raise _deny(db, row, "test_outbound_disabled", now)
    try:
        connection = connections.connection_for(db, org, settings)
    except (NotFound, Forbidden):
        raise _deny(db, row, "connection_mismatch", now) from None
    version = db.scalar(select(ProviderConnection.version).where(ProviderConnection.id == connection.connection_id))
    if (
        connection.connection_id != row.provider_connection_id
        or version != row.connection_version
        or not connection.enabled
    ):
        raise _deny(db, row, "connection_changed", now)
    recipient = db.scalar(select(ProviderTestRecipient).where(ProviderTestRecipient.id == row.recipient_id))
    if recipient is None or recipient.status != "active":
        raise _deny(db, row, "recipient_revoked", now)
    keys = contacts.keyring(settings)
    e164 = _allowlisted(settings, keys, recipient.key_id, recipient.address_digest)
    if e164 is None:
        raise _deny(db, row, "recipient_not_allowlisted", now)
    if _suppressed(db, org, keys, e164):
        raise _deny(db, row, "recipient_suppressed", now)
    if _sourced_contact(db, org, keys, e164):
        raise _deny(db, row, "recipient_is_sourced_contact", now)
    day_start = datetime.combine(now.astimezone(BUSINESS_TZ).date(), datetime.min.time(), BUSINESS_TZ)
    used_today = db.scalar(
        select(func.count()).select_from(ProviderTestSend).where(
            ProviderTestSend.organization_id == org, ProviderTestSend.state.in_(ATTEMPTED),
            ProviderTestSend.confirmed_at >= day_start,
        )
    )  # fmt: skip
    if (used_today or 0) >= DAILY_CAP:
        raise _deny(db, row, "daily_cap_reached", now)
    sender = _transport(settings, connection, clock.now)
    try:  # revalidate the template with Meta immediately before the send
        current = next(
            (t for t in sender.list_templates(name=row.template_name)
             if t.name == row.template_name and t.language == row.template_language),
            None,
        )  # fmt: skip
    except wa.ProviderCallError as exc:
        raise _deny(db, row, f"template_check_failed_{exc.error_class}", now) from None
    if current is None or current.provider_status != "APPROVED" or current.components_digest != row.components_digest:
        raise _deny(db, row, "template_changed", now)
    row.state, row.confirmed_by, row.confirmed_at = "reserved", actor.user_id, now
    row.updated_at, row.version = now, row.version + 1
    try:
        db.commit()  # reserved before any network call: a crash leaves a visible reservation, never a resend
    except IntegrityError:
        db.rollback()
        raise Conflict("another test send is in flight for this connection") from None
    parameters = [TemplateParameter(text=p) for p in row.params_json]
    body = [TemplateComponent(type="body", parameters=parameters)] if parameters else []
    intent = SendIntent(
        operation_id=row.id, organization_id=org, provider_connection_id=connection.connection_id,
        purpose="operator_test", recipient_ref=recipient.id, kind=OutboundKind.TEMPLATE,
        template_name=row.template_name, template_language=row.template_language,
        template_components=body,
        draft_revision_digest=None, approval_id=None, policy_revision=POLICY_REVISION, created_at_utc=now,
        idempotency_key=row.idempotency_key,
    )  # fmt: skip
    result, refused_class = None, None
    try:
        result = sender.send_template(intent, ResolvedRecipient(recipient_ref=recipient.id, e164=e164), current)
    except wa.ProviderCallError as exc:  # refused before any network call
        refused_class = exc.error_class
    state = "definitively_rejected" if result is None else STATE_OF[result.outcome]
    row = _lock(db, org, send_id)
    row.state, row.updated_at, row.version = state, clock.now(), row.version + 1
    if result is not None:
        row.provider_message_id, row.provider_message_status = (
            result.provider_message_id,
            result.provider_message_status,
        )
        row.error_class, row.provider_error_code = result.error_class, result.provider_error_code
    else:
        row.error_class = refused_class
    management._audit(db, actor, clock, "whatsapp.test_send_confirmed", row.id,
                      {"state": state, "error_class": row.error_class, "provider_error_code": row.provider_error_code,
                       "recipient": recipient.address_hint, "template": row.template_name},
                      target_type="provider_test_send")  # fmt: skip
    db.commit()
    return row, True


def cancel(db: Session, *, actor: Actor, clock: Clock, send_id: uuid.UUID) -> ProviderTestSend:
    account_service._require(actor, Capability.MUTATE)
    row = _lock(db, actor.organization_id, send_id)
    if row.state != "awaiting_confirmation":
        db.rollback()
        raise Conflict(f"only a preview awaiting confirmation can be cancelled (this one is {row.state})")
    row.state, row.updated_at, row.version = "cancelled", clock.now(), row.version + 1
    db.commit()
    return row


def mark_indeterminate(db: Session, *, actor: Actor, clock: Clock, send_id: uuid.UUID) -> ProviderTestSend:
    """Owner-only: a reservation that outlived its worker is recorded as unknown. It is never resent."""
    account_service._require(actor, Capability.ADMINISTER)
    row = _lock(db, actor.organization_id, send_id)
    now = clock.now()
    if row.state != "reserved" or now - row.updated_at < STALE_RESERVATION:
        db.rollback()
        raise Conflict("only a reservation older than two minutes can be marked indeterminate")
    row.state, row.error_class, row.updated_at, row.version = (
        "indeterminate",
        "provider_uncertain",
        now,
        row.version + 1,
    )
    management._audit(db, actor, clock, "whatsapp.test_send_marked_indeterminate", row.id, {},
                      target_type="provider_test_send")  # fmt: skip
    db.commit()
    return row


# --- reads -------------------------------------------------------------------------------------------------------


def get(db: Session, org: uuid.UUID, send_id: uuid.UUID) -> ProviderTestSend:
    row = db.scalar(
        select(ProviderTestSend).where(ProviderTestSend.organization_id == org, ProviderTestSend.id == send_id)
    )
    if row is None:
        raise NotFound()
    return row


def view(db: Session, row: ProviderTestSend, *, full: bool) -> dict[str, Any]:
    """Acceptance and webhook-observed delivery are reported separately; a missing webhook is never a guess."""
    timeline: list[dict[str, Any]] = []
    delivery = None
    if row.provider_message_id is not None:
        projection = db.scalar(
            select(ProviderMessageStatus).where(
                ProviderMessageStatus.provider_connection_id == row.provider_connection_id,
                ProviderMessageStatus.provider_message_id == row.provider_message_id,
            )
        )
        delivery = (
            {"status": projection.status, "conflict": projection.conflict_reason} if projection else
            {"status": "accepted_unknown_delivery", "conflict": None}
        )  # fmt: skip
        timeline = [
            {"status": o.status, "provider_timestamp": o.provider_timestamp.isoformat(),
             "observed_at": o.observed_at.isoformat(), "error_code": o.error_code}
            for o in db.scalars(
                select(ProviderStatusObservation)
                .where(ProviderStatusObservation.provider_connection_id == row.provider_connection_id,
                       ProviderStatusObservation.provider_message_id == row.provider_message_id)
                .order_by(ProviderStatusObservation.provider_timestamp)
            )
        ]  # fmt: skip
    out: dict[str, Any] = {
        "id": str(row.id), "state": row.state, "delivery": delivery, "created_at": row.created_at.isoformat(),
        "real_message": True, "label": CONFIRM_LABEL,
    }  # fmt: skip
    if not full:
        return out  # observers: redacted status only
    recipient = db.scalar(select(ProviderTestRecipient).where(ProviderTestRecipient.id == row.recipient_id))
    template = db.scalar(select(ProviderTemplate).where(ProviderTemplate.id == row.template_row_id))
    return out | {
        "template": {"name": row.template_name, "language": row.template_language, "category": row.template_category},
        "parameters": row.params_json,
        "preview_text": _render(template.body_text if template else None, row.params_json),
        "recipient": recipient.address_hint if recipient else None,
        "preview_digest": row.preview_digest, "expires_at": row.expires_at.isoformat(),
        "denial_reason": row.denial_reason, "provider_message_id": row.provider_message_id,
        "provider_message_status": row.provider_message_status, "error_class": row.error_class,
        "provider_error_code": row.provider_error_code,
        "confirmed_at": row.confirmed_at.isoformat() if row.confirmed_at else None,
        "policy_revision": row.policy_revision, "timeline": timeline,
    }  # fmt: skip


def list_sends(db: Session, org: uuid.UUID) -> list[ProviderTestSend]:
    return list(
        db.scalars(
            select(ProviderTestSend)
            .where(ProviderTestSend.organization_id == org)
            .order_by(ProviderTestSend.created_at.desc(), ProviderTestSend.id)
            .limit(50)
        )
    )


def connection_status(db: Session, org: uuid.UUID, settings: Settings) -> dict[str, Any]:
    row = db.scalar(select(ProviderConnection).where(ProviderConnection.organization_id == org))
    return {
        "mode": settings.whatsapp_mode, "graph_version": settings.whatsapp_graph_version,
        "bound": row is not None,
        "phone_number_id": f"…{row.phone_number_id[-4:]}" if row else None,
        "matches_configuration": bool(row and (row.waba_id, row.phone_number_id, row.mode)
                                      == (settings.whatsapp_waba_id, settings.whatsapp_phone_number_id,
                                          settings.whatsapp_mode)),
        "test_outbound_enabled": settings.whatsapp_test_outbound_enabled,
        "test_sending_available": settings.whatsapp_mode in ("contract_test", "provider_test"),
        "live_outbound_enabled": False, "production_outreach": "disabled until P5.5",
    }  # fmt: skip
