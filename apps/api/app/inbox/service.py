"""Read-only WhatsApp inbox (P5.4, ADR-029). Reads signed facts; never sends, replies, enrolls or grants consent.

- **Threads** are touched in the same transaction as the fact they reflect: the P5.2 processor (inbound) and the
  P5.3 reservation (test outbound). `rebuild` recomputes them from the source tables. Every write only moves
  values forward, so all three converge.
- **Unread** is derived from P5.2 arrival order (`arrival_seq > reviewed_through_seq`), never a counter: redelivery
  cannot double it, and a backdated message that arrives after a review is still unread.
- **Text** is unsealed only for the timeline response, and only within `content.RETENTION`.
"""

import base64
import binascii
import json
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import and_, func, literal, or_, select, tuple_, update
from sqlalchemy.dialects.postgresql import JSONB, insert
from sqlalchemy.orm import Session

from app.accounts import management
from app.accounts import service as account_service
from app.accounts.models import Account
from app.auth.dependencies import Capability
from app.auth.service import Actor
from app.contacts.addresses import Keyring
from app.contacts.models import Contact, SuppressionEntry
from app.core.clock import Clock
from app.core.errors import NotFound, Unprocessable
from app.inbox.models import InboxThread
from app.jobs import service as job_service
from app.whatsapp import content
from app.whatsapp.models import (
    ProviderConnection,
    ProviderEventItem,
    ProviderInboundMessage,
    ProviderMessageStatus,
    ProviderStatusObservation,
    ProviderTestRecipient,
    ProviderTestSend,
)

ATTEMPTED = ("reserved", "provider_accepted", "definitively_rejected", "indeterminate")
TEST_MODES = ("contract_test", "provider_test")
UNMATCHED = "Unmatched WhatsApp contact"


@dataclass(frozen=True)
class Party:
    connection_id: uuid.UUID
    key_id: str
    digest: str
    hint: str


# --- writes (projection) -----------------------------------------------------------------------------------------


def touch(db: Session, *, org: uuid.UUID, party: Party, at: datetime, inbound_seq: int, now: datetime) -> None:
    """Create or advance a thread. Idempotent and race-safe: one row per party, values only move forward."""
    values = {
        "id": uuid.uuid4(), "organization_id": org, "provider_connection_id": party.connection_id,
        "party_key_id": party.key_id, "party_digest": party.digest, "party_hint": party.hint,
        "last_activity_at": at, "last_inbound_seq": inbound_seq, "reviewed_through_seq": 0,
        "created_at": now, "updated_at": now, "version": 1,
    }  # fmt: skip
    statement = insert(InboxThread).values(**values)
    new = statement.excluded
    db.execute(
        statement.on_conflict_do_update(
            constraint="uq_inbox_threads_party",
            set_={
                "last_activity_at": func.greatest(InboxThread.last_activity_at, new.last_activity_at),
                "last_inbound_seq": func.greatest(InboxThread.last_inbound_seq, new.last_inbound_seq),
                "updated_at": new.updated_at,
                "version": InboxThread.version + 1,
            },  # fmt: skip
            where=or_(
                InboxThread.last_activity_at < new.last_activity_at,
                InboxThread.last_inbound_seq < new.last_inbound_seq,
            ),
        )
    )


def purge_expired(db: Session, org: uuid.UUID, connection_id: uuid.UUID, now: datetime) -> int:
    """Strip sealed text older than the retention period (the signed fact and its metadata stay)."""
    result = db.execute(
        update(ProviderEventItem)
        .where(
            ProviderEventItem.organization_id == org, ProviderEventItem.provider_connection_id == connection_id,
            ProviderEventItem.item_type == "incoming_message",
            ProviderEventItem.provider_timestamp < now - content.RETENTION,
            ProviderEventItem.normalized_json.has_key("sealed_text"),
        )
        .values(normalized_json=ProviderEventItem.normalized_json.op("-", return_type=JSONB)(literal("sealed_text")))
        .execution_options(synchronize_session=False)
    )  # fmt: skip
    return int(getattr(result, "rowcount", 0) or 0)


def rebuild(db: Session, org: uuid.UUID, connection_id: uuid.UUID, now: datetime) -> dict[str, int]:
    """Recompute every thread of a connection from the immutable sources, in one transaction (the caller commits).

    Running it any number of times, or concurrently with the processor, yields the same rows: it never moves a
    value backwards and never touches review state.
    """
    inbound = db.execute(
        select(
            ProviderInboundMessage.sender_key_id, ProviderInboundMessage.sender_digest,
            func.max(ProviderInboundMessage.sender_hint), func.max(ProviderInboundMessage.provider_timestamp),
            func.max(ProviderEventItem.arrival_seq),
        )
        .join(ProviderEventItem, ProviderEventItem.id == ProviderInboundMessage.event_item_id)
        .where(ProviderInboundMessage.organization_id == org,
               ProviderInboundMessage.provider_connection_id == connection_id)
        .group_by(ProviderInboundMessage.sender_key_id, ProviderInboundMessage.sender_digest)
    ).all()  # fmt: skip
    outbound = db.execute(
        select(
            ProviderTestRecipient.key_id, ProviderTestRecipient.address_digest,
            func.max(ProviderTestRecipient.address_hint), func.max(ProviderTestSend.confirmed_at),
        )
        .join(ProviderTestRecipient, ProviderTestRecipient.id == ProviderTestSend.recipient_id)
        .where(ProviderTestSend.organization_id == org, ProviderTestSend.provider_connection_id == connection_id,
               ProviderTestSend.confirmed_at.is_not(None))
        .group_by(ProviderTestRecipient.key_id, ProviderTestRecipient.address_digest)
    ).all()  # fmt: skip
    for key_id, digest, hint, at, seq in inbound:
        touch(db, org=org, party=Party(connection_id, key_id, digest, hint), at=at, inbound_seq=int(seq), now=now)
    for key_id, digest, hint, sent_at in outbound:
        if sent_at is None:  # excluded by the query; keeps the type honest
            continue
        touch(db, org=org, party=Party(connection_id, key_id, digest, hint), at=sent_at, inbound_seq=0, now=now)
    purged = purge_expired(db, org, connection_id, now)
    return {"inbound_parties": len(inbound), "test_parties": len(outbound), "purged_texts": purged}


# --- reads -------------------------------------------------------------------------------------------------------


def _encode(at: datetime, row_id: uuid.UUID) -> str:
    return base64.urlsafe_b64encode(json.dumps([at.isoformat(), str(row_id)]).encode()).decode()


def _decode(cursor: str | None) -> tuple[datetime, uuid.UUID] | None:
    if cursor is None:
        return None
    try:
        at, row_id = json.loads(base64.urlsafe_b64decode(cursor.encode()))
        parsed = datetime.fromisoformat(at)
        if parsed.tzinfo is None:
            raise ValueError
        return parsed, uuid.UUID(row_id)
    except (ValueError, TypeError, binascii.Error, json.JSONDecodeError):
        raise Unprocessable("CURSOR_INVALID: use the cursor returned by the previous page") from None


def _unread() -> Any:
    return (
        select(func.count())
        .select_from(ProviderInboundMessage)
        .join(ProviderEventItem, ProviderEventItem.id == ProviderInboundMessage.event_item_id)
        .where(
            ProviderInboundMessage.provider_connection_id == InboxThread.provider_connection_id,
            ProviderInboundMessage.sender_key_id == InboxThread.party_key_id,
            ProviderInboundMessage.sender_digest == InboxThread.party_digest,
            ProviderEventItem.arrival_seq > InboxThread.reviewed_through_seq,
        )
        .correlate(InboxThread)
        .scalar_subquery()
    )


def _parties(db: Session, org: uuid.UUID, threads: list[InboxThread]) -> dict[uuid.UUID, dict[str, Any]]:
    """Who each thread is, from server-side registries only. Nothing is inferred from message content."""
    keys = {(t.party_key_id, t.party_digest) for t in threads}
    if not keys:
        return {}
    contact_rows = db.execute(
        select(Contact.key_id, Contact.address_digest, Contact.id, Account.id, Account.canonical_name)
        .join(Account, and_(Account.organization_id == Contact.organization_id, Account.id == Contact.account_id))
        .where(Contact.organization_id == org, tuple_(Contact.key_id, Contact.address_digest).in_(keys))
    ).all()
    contacts = {
        (k, d): {"contact_id": str(c), "account_id": str(a), "account_name": n} for k, d, c, a, n in contact_rows
    }
    tests = {
        (k, d): label
        for k, d, label in db.execute(
            select(ProviderTestRecipient.key_id, ProviderTestRecipient.address_digest, ProviderTestRecipient.label)
            .where(ProviderTestRecipient.organization_id == org,
                   tuple_(ProviderTestRecipient.key_id, ProviderTestRecipient.address_digest).in_(keys))
        )
    }  # fmt: skip
    suppressed = {
        (k, d)
        for k, d in db.execute(
            select(SuppressionEntry.key_id, SuppressionEntry.address_digest).where(
                SuppressionEntry.organization_id == org,
                tuple_(SuppressionEntry.key_id, SuppressionEntry.address_digest).in_(keys),
            )
        )
    }
    modes = {
        i: m
        for i, m in db.execute(
            select(ProviderConnection.id, ProviderConnection.mode).where(ProviderConnection.organization_id == org)
        )
    }
    out: dict[uuid.UUID, dict[str, Any]] = {}
    for t in threads:
        key = (t.party_key_id, t.party_digest)
        contact, test_label = contacts.get(key), tests.get(key)
        party: dict[str, Any]
        if test_label is not None:
            # A registered test number is never presented as a prospect, even if it also matches a contact.
            party = {"type": "test_recipient", "label": f"TEST recipient: {test_label}",
                     "conflict": "matches_sourced_contact" if contact else None}  # fmt: skip
        elif contact is not None:
            party = {"type": "contact", "label": f"Contact at {contact['account_name']}", "conflict": None} | contact
        else:
            party = {"type": "unmatched", "label": UNMATCHED, "conflict": None}
        environment = "test" if modes.get(t.provider_connection_id) in TEST_MODES else "production"
        out[t.id] = party | {"address": t.party_hint, "suppressed": key in suppressed, "environment": environment}
    return out


def _thread_view(t: InboxThread, unread: int, party: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(t.id), "party": party, "last_activity_at": t.last_activity_at.isoformat(), "unread": unread,
        "last_inbound_seq": t.last_inbound_seq, "reviewed_through_seq": t.reviewed_through_seq,
        "reviewed_at": t.reviewed_at.isoformat() if t.reviewed_at else None, "version": t.version,
    }  # fmt: skip


def threads_page(db: Session, org: uuid.UUID, *, cursor: str | None, limit: int) -> dict[str, Any]:
    """Newest activity first; keyset by (last_activity_at, id), so ties and late arrivals page stably."""
    after = _decode(cursor)
    query = select(InboxThread, _unread()).where(InboxThread.organization_id == org)
    if after is not None:
        query = query.where(tuple_(InboxThread.last_activity_at, InboxThread.id) < tuple_(*after))
    rows = db.execute(query.order_by(InboxThread.last_activity_at.desc(), InboxThread.id.desc()).limit(limit + 1)).all()
    page = rows[:limit]
    parties = _parties(db, org, [t for t, _ in page])
    items = [_thread_view(t, int(unread), parties[t.id]) for t, unread in page]
    last = page[-1][0] if page else None
    more = len(rows) > limit and last is not None
    return {"items": items, "next_cursor": _encode(last.last_activity_at, last.id) if more and last else None}


def _thread(db: Session, org: uuid.UUID, thread_id: uuid.UUID, *, lock: bool = False) -> InboxThread:
    query = select(InboxThread).where(InboxThread.organization_id == org, InboxThread.id == thread_id)
    if lock:
        query = query.with_for_update().execution_options(populate_existing=True)
    row = db.scalar(query)
    if row is None:
        raise NotFound()
    return row


def _inbound_entry(
    m: ProviderInboundMessage, item: ProviderEventItem, keys: Keyring | None, now: datetime
) -> dict[str, Any]:
    sealed = item.normalized_json.get("sealed_text")
    text, state = None, "not_text"
    if m.kind == "text":
        if m.provider_timestamp < now - content.RETENTION:
            state = "expired"
        elif sealed is None:
            state = "not_retained"
        else:
            text = content.unseal(keys, content.aad(str(m.provider_connection_id), m.provider_message_id), sealed)
            state = "available" if text is not None else "unreadable"
    return {
        "type": "inbound", "id": str(m.id), "at": m.provider_timestamp.isoformat(), "seq": item.arrival_seq,
        "kind": m.kind, "text": text, "content": state,
        "truncated": bool(sealed.get("truncated")) if text is not None and isinstance(sealed, dict) else False,
        "stop_signal": m.stop_signal, "provenance": "verified_inbound",
    }  # fmt: skip


def _outbound_entry(db: Session, s: ProviderTestSend) -> dict[str, Any]:
    delivery: dict[str, Any] | None = None
    statuses: list[dict[str, Any]] = []
    if s.provider_message_id is not None:
        projection = db.scalar(
            select(ProviderMessageStatus).where(
                ProviderMessageStatus.provider_connection_id == s.provider_connection_id,
                ProviderMessageStatus.provider_message_id == s.provider_message_id,
            )
        )
        delivery = (
            {"status": projection.status, "conflict": projection.conflict_reason} if projection else
            {"status": "accepted_unknown_delivery", "conflict": None}
        )  # fmt: skip
        statuses = [
            {"status": o.status, "at": o.provider_timestamp.isoformat(), "error_code": o.error_code,
             "provenance": "signed_webhook"}
            for o in db.scalars(
                select(ProviderStatusObservation)
                .where(ProviderStatusObservation.provider_connection_id == s.provider_connection_id,
                       ProviderStatusObservation.provider_message_id == s.provider_message_id)
                .order_by(ProviderStatusObservation.provider_timestamp, ProviderStatusObservation.id)
            )
        ]  # fmt: skip
    assert s.confirmed_at is not None  # noqa: S101  # only attempted sends are selected
    return {
        "type": "test_outbound", "id": str(s.id), "at": s.confirmed_at.isoformat(), "state": s.state,
        "template": {"name": s.template_name, "language": s.template_language, "category": s.template_category},
        "provider_message_id": s.provider_message_id, "error_class": s.error_class, "delivery": delivery,
        "statuses": statuses, "provenance": "provider_test",
    }  # fmt: skip


def timeline(
    db: Session, org: uuid.UUID, thread_id: uuid.UUID, *, before: str | None, limit: int, keys: Keyring | None,
    now: datetime,
) -> dict[str, Any]:  # fmt: skip
    """Chronological entries (oldest first) of the newest page, or of the page before `before`."""
    thread = _thread(db, org, thread_id)
    cut = _decode(before)
    inbound_q = (
        select(ProviderInboundMessage, ProviderEventItem)
        .join(ProviderEventItem, ProviderEventItem.id == ProviderInboundMessage.event_item_id)
        .where(ProviderInboundMessage.organization_id == org,
               ProviderInboundMessage.provider_connection_id == thread.provider_connection_id,
               ProviderInboundMessage.sender_key_id == thread.party_key_id,
               ProviderInboundMessage.sender_digest == thread.party_digest)
    )  # fmt: skip
    outbound_q = (
        select(ProviderTestSend)
        .join(ProviderTestRecipient, ProviderTestRecipient.id == ProviderTestSend.recipient_id)
        .where(ProviderTestSend.organization_id == org,
               ProviderTestSend.provider_connection_id == thread.provider_connection_id,
               ProviderTestSend.state.in_(ATTEMPTED), ProviderTestSend.confirmed_at.is_not(None),
               ProviderTestRecipient.key_id == thread.party_key_id,
               ProviderTestRecipient.address_digest == thread.party_digest)
    )  # fmt: skip
    if cut is not None:
        inbound_q = inbound_q.where(tuple_(ProviderInboundMessage.provider_timestamp, ProviderInboundMessage.id) < cut)
        outbound_q = outbound_q.where(tuple_(ProviderTestSend.confirmed_at, ProviderTestSend.id) < cut)
    inbound = db.execute(
        inbound_q.order_by(ProviderInboundMessage.provider_timestamp.desc(), ProviderInboundMessage.id.desc())
        .limit(limit + 1)
    ).all()  # fmt: skip
    outbound = db.scalars(
        outbound_q.order_by(ProviderTestSend.confirmed_at.desc(), ProviderTestSend.id.desc()).limit(limit + 1)
    ).all()
    merged: list[tuple[datetime, uuid.UUID, Any]] = [(m.provider_timestamp, m.id, (m, e)) for m, e in inbound]
    merged += [(s.confirmed_at, s.id, s) for s in outbound if s.confirmed_at is not None]
    merged.sort(key=lambda r: (r[0], str(r[1])), reverse=True)
    page = merged[:limit]
    entries = [
        _inbound_entry(src[0], src[1], keys, now) if isinstance(src, tuple) else _outbound_entry(db, src)
        for _at, _id, src in reversed(page)
    ]
    oldest = page[-1] if page else None
    party = _parties(db, org, [thread])[thread.id]
    unread = int(db.scalar(select(_unread()).select_from(InboxThread).where(InboxThread.id == thread.id)) or 0)
    return {
        "thread": _thread_view(thread, unread, party),
        "entries": entries,
        "before_cursor": _encode(oldest[0], oldest[1]) if oldest and len(merged) > limit else None,
        "read_only": True,
    }


# --- the one local action ----------------------------------------------------------------------------------------


def mark_reviewed(
    db: Session, *, actor: Actor, clock: Clock, thread_id: uuid.UUID, through_seq: int
) -> tuple[InboxThread, bool]:
    """Owner/operator: record that inbound messages up to `through_seq` were reviewed. Local only, audited once.

    Monotonic and idempotent: a replay or an older value changes nothing; a value beyond what exists is clamped,
    so a message that arrives later stays unread.
    """
    account_service._require(actor, Capability.MUTATE)
    thread = _thread(db, actor.organization_id, thread_id, lock=True)
    through = min(through_seq, thread.last_inbound_seq)
    if through <= thread.reviewed_through_seq:
        db.rollback()
        return thread, False
    now = clock.now()
    previous = thread.reviewed_through_seq
    thread.reviewed_through_seq, thread.reviewed_by, thread.reviewed_at = through, actor.user_id, now
    thread.updated_at, thread.version = now, thread.version + 1
    management._audit(db, actor, clock, "inbox.thread_reviewed", thread.id,
                      {"from_seq": previous, "through_seq": through}, target_type="inbox_thread")  # fmt: skip
    db.commit()
    return thread, True


def request_rebuild(db: Session, *, actor: Actor, clock: Clock, environment: str) -> uuid.UUID:
    """Owner-only: enqueue `inbox.rebuild` for the organization's connection (audited)."""
    account_service._require(actor, Capability.ADMINISTER)
    connection = db.scalar(
        select(ProviderConnection).where(ProviderConnection.organization_id == actor.organization_id)
    )
    if connection is None:
        raise NotFound()
    now = clock.now()
    receipt = job_service.enqueue_job(
        db, organization_id=actor.organization_id, environment=environment, job_type="inbox.rebuild",
        schema_version=1, payload={"connection_id": str(connection.id)},
        idempotency_key=f"inbox.rebuild.{connection.id}.{int(now.timestamp() * 1000)}", clock=clock,
    )  # fmt: skip
    management._audit(db, actor, clock, "inbox.rebuild_requested", connection.id, {"job_id": str(receipt.job_id)},
                      target_type="provider_connection")  # fmt: skip
    db.commit()
    return receipt.job_id
