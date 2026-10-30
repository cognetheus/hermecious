"""Durable webhook inbox and idempotent processor (P5.2, ADR-027). Receives facts; never sends or replies.

**Receive** (inside the webhook request, after the signature check):
- one envelope row (a body digest and counts);
- one item row per *logical* fact, deduplicated per connection by `logical_key`;
- one outbox-coupled `provider_inbox.process` job per affected connection.

All of it commits before the 200, so a database failure becomes a 5xx and Meta retries.

**Process** (worker): one pending item per transaction, claimed with `SKIP LOCKED`. The domain change and the
processed marker commit together. Domain rows are unique on the provider message id, so a redelivery or two
racing workers produce one logical result.
- **Statuses:** every observation is kept; the projection never regresses, and contradictions are flagged.
- **Inbound:** sender stored only as a keyed digest; a known contact gets a verified service-window time
  (never consent); an authenticated STOP suppresses the number (P4.3); an unknown sender stays unassigned.
"""

import hashlib
import logging
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.accounts import management
from app.auth.models import Role
from app.auth.service import Actor
from app.contacts import addresses
from app.contacts import service as contacts
from app.contacts.models import Contact, SuppressionEntry
from app.core.clock import FixedClock
from app.core.errors import DependencyUnavailable
from app.core.settings import Settings
from app.jobs import registry as job_registry
from app.jobs import service as job_service
from app.whatsapp import webhook
from app.whatsapp.models import (
    ProviderConnection,
    ProviderEventItem,
    ProviderInboundMessage,
    ProviderMessageStatus,
    ProviderServiceWindow,
    ProviderStatusObservation,
    ProviderWebhookEnvelope,
)

logger = logging.getLogger("app.whatsapp")
JOB_TYPE, JOB_VERSION = "provider_inbox.process", 1
BATCH = 200
_RANK = {"sent": 1, "delivered": 2, "read": 3}


# --- receive -------------------------------------------------------------------------------------------------


def _bound(db: Session, settings: Settings, items: list[webhook.Item]) -> dict[str, ProviderConnection]:
    """phone_number_id -> connection, only for the *configured* binding (WABA, phone and mode must all match)."""
    phones = {i.phone_number_id for i in items}
    if not phones:
        return {}
    rows = db.scalars(
        select(ProviderConnection).where(
            ProviderConnection.provider == "meta_whatsapp", ProviderConnection.phone_number_id.in_(phones)
        )
    )
    return {
        r.phone_number_id: r
        for r in rows
        if r.enabled and r.phone_number_id == settings.whatsapp_phone_number_id and r.mode == settings.whatsapp_mode
    }


def receive(db: Session, *, settings: Settings, now: datetime, raw: bytes, request_id: str | None) -> dict[str, int]:
    """Persist a signature-verified body. Commits; raises on storage failure (the caller answers 5xx)."""
    parsed = webhook.parse(raw, now)
    counts = dict(parsed.counts) | {"accepted": 0, "duplicates": 0, "unmapped": 0, "quarantined": 0}
    connections = _bound(db, settings, parsed.items)
    keys = contacts.keyring(settings) if any(i.sender_e164 for i in parsed.items) else None
    envelope = ProviderWebhookEnvelope(
        provider="meta_whatsapp", body_sha256=hashlib.sha256(raw).hexdigest(), parse_status="accepted",
        quarantine_reason=parsed.quarantine_reason, counts_json={}, request_id=request_id, received_at=now,
    )  # fmt: skip
    db.add(envelope)
    db.flush()
    touched: set[uuid.UUID] = set()
    for item in parsed.items:
        connection = connections.get(item.phone_number_id)
        if connection is None or connection.waba_id != item.waba_id:
            counts["unmapped"] += 1  # never attached to any organization; nothing about it is stored
            continue
        normalized = dict(item.normalized)
        if item.sender_e164 is not None and keys is not None:
            key_id, key = keys.current
            normalized |= {
                "sender_key_id": key_id,
                "sender_digest": addresses.digest(key, item.sender_e164),
                "sender_hint": addresses.mask(item.sender_e164),
            }
        state = "quarantined" if item.quarantine else "pending"
        inserted = db.scalar(
            insert(ProviderEventItem)
            .values(
                id=uuid.uuid4(), organization_id=connection.organization_id, provider_connection_id=connection.id,
                envelope_id=envelope.id, item_type=item.item_type,
                logical_key=item.logical_key(str(connection.id)), provider_message_id=item.provider_message_id,
                provider_timestamp=item.provider_timestamp, normalized_json=normalized, processing_status=state,
                error_class=item.quarantine, attempts=0, created_at=now,
            )
            .on_conflict_do_nothing(constraint="uq_provider_event_items_logical")
            .returning(ProviderEventItem.id)
        )  # fmt: skip
        if inserted is None:
            counts["duplicates"] += 1
        elif state == "quarantined":
            counts["quarantined"] += 1
        else:
            counts["accepted"] += 1
            touched.add(connection.id)
    for connection_id in sorted(touched, key=str):
        connection = next(c for c in connections.values() if c.id == connection_id)
        job_service.enqueue_job(
            db, organization_id=connection.organization_id, environment=settings.environment, job_type=JOB_TYPE,
            schema_version=JOB_VERSION, payload={"connection_id": str(connection_id)},
            idempotency_key=f"provider_inbox.{connection_id}.{envelope.id}", clock=FixedClock(now),
        )  # fmt: skip
    if not counts["accepted"] and not counts["duplicates"]:
        envelope.parse_status = "quarantined"
        envelope.quarantine_reason = parsed.quarantine_reason or ("unmapped" if counts["unmapped"] else "no_items")
    envelope.counts_json = counts
    db.commit()  # durable before the HTTP 200
    logger.info("whatsapp.webhook_received", extra={"context": {"envelope_id": str(envelope.id), **counts}})
    return counts


# --- process -------------------------------------------------------------------------------------------------


def project(current: str | None, incoming: str) -> tuple[str, str | None]:
    """Next projected status and an optional conflict reason. Never regresses; contradictions are flagged."""
    if incoming == "unknown":
        return current or "unknown", None
    if current is None or current == "unknown":
        return incoming, None
    if incoming == "failed":
        if current in ("delivered", "read"):
            return current, "failed_after_delivered"  # keep the evidence, surface the contradiction
        return "failed", None
    if current == "failed":
        return incoming, "success_after_failed"  # a later provider-confirmed success is recorded, and flagged
    return (incoming, None) if _RANK[incoming] > _RANK[current] else (current, None)


def _status(db: Session, item: ProviderEventItem, now: datetime) -> None:
    assert item.provider_message_id is not None and item.provider_timestamp is not None  # noqa: S101  # quarantined otherwise
    incoming = item.normalized_json["status"]
    db.execute(
        insert(ProviderStatusObservation)
        .values(
            id=uuid.uuid4(), organization_id=item.organization_id, provider_connection_id=item.provider_connection_id,
            event_item_id=item.id, provider_message_id=item.provider_message_id, status=incoming,
            error_code=item.normalized_json.get("error_code"), provider_timestamp=item.provider_timestamp,
            observed_at=now,
        )
        .on_conflict_do_nothing(constraint="uq_provider_status_observations_item")
    )  # fmt: skip
    db.execute(
        insert(ProviderMessageStatus)
        .values(
            id=uuid.uuid4(), organization_id=item.organization_id, provider_connection_id=item.provider_connection_id,
            provider_message_id=item.provider_message_id, status="unknown",
            last_provider_timestamp=item.provider_timestamp, conflict=False, observations=1, updated_at=now, version=1,
        )
        .on_conflict_do_nothing(constraint="uq_provider_message_status_wamid")
    )  # fmt: skip
    row = db.scalar(
        select(ProviderMessageStatus)
        .where(
            ProviderMessageStatus.provider_connection_id == item.provider_connection_id,
            ProviderMessageStatus.provider_message_id == item.provider_message_id,
        )
        .with_for_update()
    )
    assert row is not None  # noqa: S101
    seen = int(
        db.scalar(
            select(func.count())
            .select_from(ProviderStatusObservation)
            .where(
                ProviderStatusObservation.provider_connection_id == item.provider_connection_id,
                ProviderStatusObservation.provider_message_id == item.provider_message_id,
            )
        )
        or 1
    )
    status, conflict = project(row.status, incoming)  # a fresh row starts as "unknown" (no information yet)
    row.status, row.observations, row.updated_at, row.version = status, seen, now, row.version + 1
    row.last_provider_timestamp = max(row.last_provider_timestamp, item.provider_timestamp)
    if conflict:
        row.conflict, row.conflict_reason = True, conflict


def _inbound(db: Session, item: ProviderEventItem, connection: ProviderConnection, now: datetime) -> None:
    n = item.normalized_json
    assert item.provider_message_id is not None and item.provider_timestamp is not None  # noqa: S101
    org = item.organization_id
    contact = db.scalar(
        select(Contact).where(
            Contact.organization_id == org, Contact.channel == "whatsapp", Contact.key_id == n["sender_key_id"],
            Contact.address_digest == n["sender_digest"],
        )
    )  # fmt: skip
    created = db.scalar(
        insert(ProviderInboundMessage)
        .values(
            id=uuid.uuid4(), organization_id=org, provider_connection_id=connection.id, event_item_id=item.id,
            provider_message_id=item.provider_message_id, sender_key_id=n["sender_key_id"],
            sender_digest=n["sender_digest"], sender_hint=n["sender_hint"],
            contact_id=contact.id if contact else None, assignment="contact" if contact else "unassigned",
            kind=n["kind"], text_length=n.get("text_length"), stop_signal=bool(n.get("stop_signal")),
            provider_timestamp=item.provider_timestamp, received_at=item.created_at,
        )
        .on_conflict_do_nothing(constraint="uq_provider_inbound_wamid")
        .returning(ProviderInboundMessage.id)
    )  # fmt: skip
    if created is None:
        return  # this logical message was already recorded: no second side effect
    if contact is not None:  # verified service-window provenance only: max(prior, this), never marketing consent
        db.execute(
            insert(ProviderServiceWindow)
            .values(
                id=uuid.uuid4(), organization_id=org, contact_id=contact.id, provider_connection_id=connection.id,
                last_verified_inbound_at=item.provider_timestamp, provider_message_id=item.provider_message_id,
                updated_at=now,
            )
            .on_conflict_do_update(
                constraint="uq_provider_service_windows_contact",
                set_={"last_verified_inbound_at": item.provider_timestamp,
                      "provider_message_id": item.provider_message_id, "updated_at": now},
                where=ProviderServiceWindow.last_verified_inbound_at < item.provider_timestamp,
            )
        )  # fmt: skip
    if n.get("stop_signal"):  # authenticated opt-out: suppress the number (P4.3); never reopened automatically
        suppressed = db.scalar(
            insert(SuppressionEntry)
            .values(
                id=uuid.uuid4(), organization_id=org, channel="whatsapp", key_id=n["sender_key_id"],
                address_digest=n["sender_digest"], address_hint=n["sender_hint"], reason="opt_out",
                contact_id=contact.id if contact else None, created_by=connection.created_by, created_at=now,
            )
            .on_conflict_do_nothing(constraint="uq_suppression_address")
            .returning(SuppressionEntry.id)
        )  # fmt: skip
        if suppressed is not None:
            accountable = Actor(user_id=connection.created_by, organization_id=org, role=Role.OWNER,
                                session_id=uuid.uuid4(), verifier="")  # fmt: skip
            management._audit(
                db, accountable, FixedClock(now), "contact.suppressed",
                contact.id if contact else connection.id,
                {"reason": "opt_out", "source": "whatsapp_inbound_stop",
                 "provider_message_id": item.provider_message_id},
                target_type="contact" if contact else "provider_connection",
            )  # fmt: skip


def handle(db: Session, ctx: job_registry.JobContext, payload: Any, settings: Settings) -> dict[str, Any]:
    org, connection_id = ctx.organization_id, uuid.UUID(str(payload.connection_id))
    connection = db.scalar(
        select(ProviderConnection).where(
            ProviderConnection.organization_id == org, ProviderConnection.id == connection_id
        )
    )
    if connection is None:
        raise job_registry.PermanentJobError("connection_not_found")
    done = failed = 0
    while done + failed < BATCH:
        job_registry.keep_alive(ctx)
        item = db.scalar(
            select(ProviderEventItem)
            .where(
                ProviderEventItem.organization_id == org,
                ProviderEventItem.provider_connection_id == connection_id,
                ProviderEventItem.processing_status == "pending",
            )
            .order_by(ProviderEventItem.arrival_seq)  # Meta's delivery order
            .limit(1)
            .with_for_update(skip_locked=True)
        )
        if item is None:
            break
        item_id = item.id
        try:
            if item.item_type == "delivery_status":
                _status(db, item, ctx.now)
            elif item.item_type == "incoming_message":
                _inbound(db, item, connection, ctx.now)
            item.processing_status, item.processed_at, item.attempts = "processed", ctx.now, item.attempts + 1
            db.commit()  # the domain change and the processed marker, together
            done += 1
        except DependencyUnavailable:
            db.rollback()
            raise job_registry.TransientJobError("storage_unavailable") from None
        except Exception:  # a poison item is parked, never retried forever and never blocking the rest
            db.rollback()
            logger.exception("whatsapp.inbox_item_failed", extra={"context": {"item_id": str(item_id)}})
            db.execute(
                update(ProviderEventItem)
                .where(ProviderEventItem.id == item_id, ProviderEventItem.processing_status == "pending")
                .values(processing_status="failed", error_class="unknown", attempts=ProviderEventItem.attempts + 1)
            )
            db.commit()
            failed += 1
    return {"connection_id": str(connection_id), "processed": done, "failed": failed}
