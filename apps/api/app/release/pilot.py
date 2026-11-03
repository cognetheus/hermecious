"""The operator-only 1:1 production pilot send (P5.5, ADR-030). Fake transports only in tests; nothing here runs
unless every independent gate is open at confirmation time.

**Preview** (owner or operator): the recipient, purpose and template come only from the P4.4 approval of the exact
draft revision. The approval names a contact and a `meta:<template id>`; the request gives only the draft and the
parameters. The preview stores an exact digest, a one-time nonce (hash only) and a 10-minute expiry.

**Confirm** (owner, CSRF, digest + nonce), re-checked in this order, immediately before the network boundary:
1. the deploy-time live gate (production environment, production mode, `HERMECIOUS_LIVE_OUTBOUND_ENABLED`);
2. the pilot authorization (active, not paused or expired, same connection) and its daily cap;
3. readiness recomputed now must equal the authorized assessment (status and digest);
4. the P4.4 approval is still current for this exact revision;
5. P4.3 `decide()` (consent scope and freshness, suppression, kill switch, quiet hours, campaign and P3.4 gate,
   human owner, provider template status) must allow;
6. Meta's live catalog still has the template APPROVED with the same components.

Then it reserves (commit), re-reads the kill switch and live gate, makes exactly one Graph call and records
`provider_accepted` (not delivered), `definitively_rejected` or `indeterminate`. Nothing is ever resent.
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
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.accounts import management
from app.accounts import service as account_service
from app.approvals import service as approvals
from app.auth.dependencies import Capability
from app.auth.service import Actor
from app.contacts import addresses
from app.contacts import service as contacts
from app.core.clock import BUSINESS_TZ, Clock
from app.core.errors import Conflict, NotFound, Unprocessable
from app.core.settings import Settings
from app.drafts.models import Draft
from app.eligibility import service as eligibility
from app.release import service as release
from app.release.models import PilotAuthorization, PilotSend
from app.whatsapp import service as connections
from app.whatsapp import transport as wa
from app.whatsapp.contracts import (
    OutboundKind,
    ProviderConnectionView,
    ResolvedRecipient,
    SendIntent,
    TemplateComponent,
    TemplateParameter,
)
from app.whatsapp.models import ProviderConnection, ProviderMessageStatus, ProviderTemplate

POLICY_REVISION = "whatsapp-pilot-1.0"
CONFIRM_LABEL = "This sends ONE REAL WhatsApp message to a real opted-in contact."
PREVIEW_TTL = timedelta(minutes=10)
STALE_RESERVATION = timedelta(minutes=2)
ATTEMPTED = ("reserved", "provider_accepted", "definitively_rejected", "indeterminate")
STATE_OF = {"accepted": "provider_accepted", "definitive_rejected": "definitively_rejected",
            "indeterminate": "indeterminate"}  # fmt: skip
CATEGORY_FOR = {"marketing": "MARKETING", "utility": "UTILITY"}
# Circuit breaker (P5.5 step 5): these provider errors pause the pilot automatically; a person resumes it.
BREAKER = ("provider_auth", "provider_quota")


def _digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()


# The only production send constructor. Tests replace it with a local fake; nothing else may build one.
def _transport(settings: Settings, connection: ProviderConnectionView, now: Callable[[], datetime]) -> Any:
    return wa.build_transport(settings, connection, now, purpose="production_send")


def _active_authorization(db: Session, org: uuid.UUID, now: datetime) -> PilotAuthorization | None:
    return db.scalar(
        select(PilotAuthorization)
        .where(PilotAuthorization.organization_id == org, PilotAuthorization.status == "active",
               PilotAuthorization.expires_at > now)
        .order_by(PilotAuthorization.created_at.desc())
        .limit(1)
    )  # fmt: skip


def _approval(db: Session, org: uuid.UUID, draft_id: uuid.UUID, now: datetime, settings: Settings) -> Any:
    draft = db.scalar(select(Draft).where(Draft.organization_id == org, Draft.id == draft_id))
    if draft is None:
        raise NotFound()
    status = approvals.status(db, draft, now, settings)
    return draft, status


def _template(db: Session, org: uuid.UUID, connection_id: uuid.UUID, ref: str | None) -> ProviderTemplate | None:
    if not ref or not ref.startswith("meta:"):
        return None
    return db.scalar(
        select(ProviderTemplate).where(
            ProviderTemplate.organization_id == org, ProviderTemplate.provider_connection_id == connection_id,
            ProviderTemplate.template_id == ref.removeprefix("meta:"),
        )
    )  # fmt: skip


# --- preview -----------------------------------------------------------------------------------------------------


def preview(
    db: Session, *, actor: Actor, clock: Clock, settings: Settings, draft_id: uuid.UUID, parameters: list[str],
    idempotency_key: str,
) -> tuple[PilotSend, str | None]:  # fmt: skip
    account_service._require(actor, Capability.MUTATE)
    org, now = actor.organization_id, clock.now()
    request = _digest(["pilot_preview", str(draft_id), parameters])
    prior = db.scalar(select(PilotSend).where(PilotSend.organization_id == org,
                                              PilotSend.idempotency_key == idempotency_key))  # fmt: skip
    if prior is not None:
        if prior.request_digest != request:
            raise Conflict("idempotency_key was already used for a different pilot send")
        return prior, None
    authorization = _active_authorization(db, org, now)
    if authorization is None:
        raise Conflict("no active pilot authorization (a ready report alone never permits sending)")
    connection = connections.connection_for(db, org, settings)
    if connection.connection_id != authorization.provider_connection_id:
        raise Conflict("the pilot authorization is for another connection")
    draft, status = _approval(db, org, draft_id, now, settings)
    review = status.get("review")
    if status["state"] != "approved_content" or review is None:
        raise Conflict(f"the draft has no current content approval ({status['state']}: "
                       f"{', '.join(status['stale_reasons']) or 'none'})")  # fmt: skip
    if review.get("purpose") != authorization.purpose:
        raise Conflict("the approval's purpose is outside this pilot authorization")
    template = _template(db, org, connection.connection_id, review.get("template_ref"))
    if template is None:
        raise Conflict("the approval does not reference a synced Meta template (meta:<template id>)")
    if template.provider_status != "APPROVED" or not template.supported or template.header_parameter_count:
        raise Conflict("the Meta template is not currently APPROVED with supported components")
    if template.category != CATEGORY_FOR[authorization.purpose]:
        raise Conflict("the Meta template category does not match the pilot purpose")
    try:
        typed = [TemplateParameter(text=p) for p in parameters]
    except ValidationError:
        raise Unprocessable("PARAMETERS_INVALID: plain text only (no links, numbers or control characters)") from None
    if len(typed) != template.body_parameter_count:
        raise Unprocessable("PARAMETERS_INVALID: the count does not match the approved template's placeholders")
    contact_id = uuid.UUID(review["contact_id"])
    preview_digest = _digest({
        "draft": str(draft.id), "revision": draft.revision, "approval": review["id"], "contact": str(contact_id),
        "template_id": template.template_id, "language": template.language,
        "components_digest": template.components_digest, "parameters": parameters,
        "authorization": str(authorization.id),
    })  # fmt: skip
    nonce = secrets.token_urlsafe(32)
    row = PilotSend(
        organization_id=org, authorization_id=authorization.id, provider_connection_id=connection.connection_id,
        contact_id=contact_id, draft_id=draft.id, draft_revision=draft.revision,
        approval_id=uuid.UUID(review["id"]), template_row_id=template.id, template_name=template.name,
        template_language=template.language, template_category=template.category,
        components_digest=template.components_digest, params_json=parameters, purpose=authorization.purpose,
        preview_digest=preview_digest, nonce_digest=hashlib.sha256(nonce.encode()).hexdigest(),
        expires_at=now + PREVIEW_TTL, state="awaiting_confirmation", requested_by=actor.user_id,
        idempotency_key=idempotency_key, request_digest=request, simulated_transport=False,
        created_at=now, updated_at=now, version=1,
    )  # fmt: skip
    db.add(row)
    try:
        db.flush()
        management._audit(db, actor, clock, "release.pilot_previewed", row.id,
                          {"draft": str(draft.id), "revision": draft.revision, "template": template.name},
                          target_type="pilot_send")  # fmt: skip
        db.commit()
    except IntegrityError:
        db.rollback()
        raise Conflict("a concurrent preview used this idempotency key; reload") from None
    return row, nonce


# --- confirm -----------------------------------------------------------------------------------------------------


def _deny(db: Session, row: PilotSend, reason: str, now: datetime) -> Conflict:
    row.state, row.denial_reason, row.updated_at, row.version = "denied", reason[:80], now, row.version + 1
    db.commit()
    return Conflict(f"pilot send denied: {reason}")


def _lock(db: Session, org: uuid.UUID, send_id: uuid.UUID) -> PilotSend:
    row = db.scalar(
        select(PilotSend)
        .where(PilotSend.organization_id == org, PilotSend.id == send_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if row is None:
        raise NotFound()
    return row


def confirm(
    db: Session, *, actor: Actor, clock: Clock, settings: Callable[[], Settings], send_id: uuid.UUID,
    preview_digest: str, nonce: str, recipient_number: str,
) -> tuple[PilotSend, bool]:  # fmt: skip
    """Owner-only. `settings` is read again after the reservation, so a kill switch flipped mid-flight still stops
    the call. `recipient_number` must hash to the approved contact's stored digest; it is used once, in memory, and
    never stored or logged. Returns (row, sent_now)."""
    account_service._require(actor, Capability.ADMINISTER)
    org = actor.organization_id
    row = _lock(db, org, send_id)
    nonce_ok = secrets.compare_digest(hashlib.sha256(nonce.encode()).hexdigest(), row.nonce_digest)
    digest_ok = secrets.compare_digest(preview_digest, row.preview_digest)
    if row.state != "awaiting_confirmation":
        db.rollback()
        if nonce_ok and digest_ok:
            return row, False  # a replay: the recorded outcome stands, never a second send
        raise Conflict(f"this pilot send is {row.state}")
    if not (nonce_ok and digest_ok):
        db.rollback()
        raise Conflict("the confirmation does not match the preview you were shown")
    now, current = clock.now(), settings()
    contact = contacts.get(db, org, row.contact_id)
    e164 = _verified_number(current, contact, recipient_number)
    if e164 is None:  # not consumed: a mistyped number can be corrected; it can never reach anyone else
        db.rollback()
        raise Conflict("the number does not match the approved contact")
    if now >= row.expires_at:
        row.state, row.updated_at, row.version = "expired", now, row.version + 1
        db.commit()
        raise Conflict("the preview expired; create a new one")
    if (gate := release.live_gate(current)) is not None:
        raise _deny(db, row, gate, now)
    authorization = db.scalar(select(PilotAuthorization).where(PilotAuthorization.id == row.authorization_id))
    if authorization is None or authorization.status != "active" or now >= authorization.expires_at:
        reason = authorization.pause_reason if authorization and authorization.status == "paused" else None
        raise _deny(db, row, f"pilot_{reason or 'not_active'}", now)
    try:
        connection = connections.connection_for(db, org, current)
    except (NotFound, Exception):  # noqa: BLE001  # any binding problem is a denial, never a send
        raise _deny(db, row, "connection_mismatch", now) from None
    if connection.connection_id != row.provider_connection_id or not connection.enabled:
        raise _deny(db, row, "connection_changed", now)
    day_start = datetime.combine(now.astimezone(BUSINESS_TZ).date(), datetime.min.time(), BUSINESS_TZ)
    used = db.scalar(
        select(func.count()).select_from(PilotSend).where(
            PilotSend.authorization_id == authorization.id, PilotSend.state.in_(ATTEMPTED),
            PilotSend.confirmed_at >= day_start,
        )
    )  # fmt: skip
    if (used or 0) >= authorization.max_per_day:
        raise _deny(db, row, "daily_cap_reached", now)
    status, digest = release.current_digest(db, org, current, now)
    if (status, digest) != ("ready_for_operator_review", authorization.assessment_digest):
        raise _deny(db, row, "readiness_invalidated", now)
    draft, approval = _approval(db, org, row.draft_id, now, current)
    review = approval.get("review")
    if (
        approval["state"] != "approved_content"
        or review is None
        or review["id"] != str(row.approval_id)
        or draft.revision != row.draft_revision
    ):
        raise _deny(db, row, "approval_stale", now)  # fmt: skip
    template = db.scalar(select(ProviderTemplate).where(ProviderTemplate.id == row.template_row_id))
    if template is None:  # pragma: no cover  # composite FK
        raise _deny(db, row, "template_missing", now)
    decision = eligibility.decide(
        db, org=org, now=now, settings=current, contact_id=row.contact_id, purpose=row.purpose,  # type: ignore[arg-type]
        campaign_id=draft.campaign_id, template_ref=f"meta:{template.template_id}", inbound_ref=None,
    )  # fmt: skip
    if decision["decision"] != "allow_for_simulation":  # the P4.3 rule set is the authority for this contact
        codes = ",".join(r["code"] for r in decision["reasons"]) or decision["decision"]
        raise _deny(db, row, f"eligibility_{decision['decision']}:{codes}", now)
    sender = _transport(current, connection, clock.now)
    try:  # Meta's live catalog immediately before the send
        live = next(
            (t for t in sender.list_templates(name=row.template_name)
             if t.name == row.template_name and t.language == row.template_language),
            None,
        )  # fmt: skip
    except wa.ProviderCallError as exc:
        raise _deny(db, row, f"template_check_failed_{exc.error_class}", now) from None
    if live is None or live.provider_status != "APPROVED" or live.components_digest != row.components_digest:
        raise _deny(db, row, "template_changed", now)
    row.state, row.confirmed_by, row.confirmed_at = "reserved", actor.user_id, now
    row.simulated_transport = not sender.real_network
    row.updated_at, row.version = now, row.version + 1
    try:
        db.commit()  # reserved before any network call: a crash leaves a visible reservation, never a resend
    except IntegrityError:
        db.rollback()
        raise Conflict("another pilot send is in flight for this connection") from None
    # Everything that can stop unsent work is read again between the reservation and the call: the global stop, the
    # live gate, the pilot (paused for human takeover or a quality alert, revoked, expired) and the connection.
    latest = settings()
    db.expire_all()
    authorization_now = db.scalar(select(PilotAuthorization).where(PilotAuthorization.id == row.authorization_id))
    connection_now = db.scalar(select(ProviderConnection).where(ProviderConnection.id == row.provider_connection_id))
    if (
        latest.outreach_kill_switch
        or release.live_gate(latest) is not None
        or authorization_now is None
        or authorization_now.status != "active"
        or clock.now() >= authorization_now.expires_at
        or connection_now is None
        or not connection_now.enabled
    ):
        row = _lock(db, org, send_id)
        row.state, row.denial_reason, row.updated_at, row.version = (
            "denied", "stopped_before_send", clock.now(), row.version + 1,
        )  # fmt: skip
        db.commit()
        raise Conflict("pilot send stopped before the network call (kill switch, live gate, pause or connection)")
    parameters = [TemplateParameter(text=p) for p in row.params_json]
    body = [TemplateComponent(type="body", parameters=parameters)] if parameters else []
    intent = SendIntent(
        operation_id=row.id, organization_id=org, provider_connection_id=connection.connection_id,
        purpose=row.purpose, recipient_ref=row.contact_id, kind=OutboundKind.TEMPLATE,  # type: ignore[arg-type]
        template_name=row.template_name, template_language=row.template_language, template_components=body,
        draft_revision_digest=row.preview_digest, approval_id=row.approval_id, policy_revision=POLICY_REVISION,
        created_at_utc=now, idempotency_key=row.idempotency_key,
    )  # fmt: skip
    result, refused = None, None
    try:
        result = sender.send_template(intent, ResolvedRecipient(recipient_ref=row.contact_id, e164=e164), live)
    except wa.ProviderCallError as exc:  # refused before any network call
        refused = exc.error_class
    row = _lock(db, org, send_id)
    row.state = "definitively_rejected" if result is None else STATE_OF[result.outcome]
    row.updated_at, row.version = clock.now(), row.version + 1
    if result is not None:
        row.provider_message_id, row.provider_message_status = (
            result.provider_message_id,
            result.provider_message_status,
        )
        row.error_class, row.provider_error_code = result.error_class, result.provider_error_code
    else:
        row.error_class = refused
    if row.error_class in BREAKER:  # auth or quota trouble: stop the pilot until a person looks
        paused = db.scalar(
            select(PilotAuthorization).where(PilotAuthorization.id == row.authorization_id).with_for_update()
        )
        if paused is not None and paused.status == "active":
            paused.status, paused.pause_reason = "paused", "provider_error"
            paused.updated_at, paused.version = clock.now(), paused.version + 1
            management._audit(db, actor, clock, "release.pilot_paused", paused.id,
                              {"reason": "provider_error", "error_class": row.error_class},
                              target_type="pilot_authorization")  # fmt: skip
    management._audit(db, actor, clock, "release.pilot_confirmed", row.id,
                      {"state": row.state, "error_class": row.error_class, "contact": contact.address_hint,
                       "template": row.template_name, "simulated_transport": row.simulated_transport},
                      target_type="pilot_send")  # fmt: skip
    db.commit()
    return row, True


def _verified_number(settings: Settings, contact: Any, typed: str) -> str | None:
    """P4.3 stores a number only as a keyed digest, so the owner types it; it must match the approved contact."""
    try:
        e164 = addresses.canonical(typed)
    except addresses.AddressError:
        return None
    key = dict(contacts.keyring(settings).keys).get(contact.key_id)
    if key is None or not secrets.compare_digest(addresses.digest(key, e164), contact.address_digest):
        return None
    return e164


def cancel(db: Session, *, actor: Actor, clock: Clock, send_id: uuid.UUID) -> PilotSend:
    account_service._require(actor, Capability.MUTATE)
    row = _lock(db, actor.organization_id, send_id)
    if row.state != "awaiting_confirmation":
        db.rollback()
        raise Conflict(f"only a preview awaiting confirmation can be cancelled (this one is {row.state})")
    row.state, row.updated_at, row.version = "cancelled", clock.now(), row.version + 1
    db.commit()
    return row


def mark_indeterminate(db: Session, *, actor: Actor, clock: Clock, send_id: uuid.UUID) -> PilotSend:
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
    management._audit(db, actor, clock, "release.pilot_marked_indeterminate", row.id, {}, target_type="pilot_send")
    db.commit()
    return row


def view(db: Session, row: PilotSend) -> dict[str, Any]:
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
    return {
        "id": str(row.id), "state": row.state, "denial_reason": row.denial_reason, "delivery": delivery,
        "template": {"name": row.template_name, "language": row.template_language, "category": row.template_category},
        "parameters": row.params_json, "draft_id": str(row.draft_id), "draft_revision": row.draft_revision,
        "preview_digest": row.preview_digest, "expires_at": row.expires_at.isoformat(),
        "provider_message_id": row.provider_message_id, "error_class": row.error_class,
        "simulated_transport": row.simulated_transport, "label": CONFIRM_LABEL, "real_message": True,
    }  # fmt: skip


def get(db: Session, org: uuid.UUID, send_id: uuid.UUID) -> PilotSend:
    row = db.scalar(select(PilotSend).where(PilotSend.organization_id == org, PilotSend.id == send_id))
    if row is None:
        raise NotFound()
    return row
