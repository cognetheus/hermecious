"""Reply proposals for signed inbound messages (P6.2, ADR-032). Drafts for human review; never a send.

- **Gate:** `HERMECIOUS_REPLY_PROPOSALS`. While P6.1 is not verified, only `fixtures` (outside production, synthetic
  data) or an explicitly signed-off `inbound` mode can generate; `off` refuses.
- **Binding:** the message is the caller's organization's signed P5.2 inbound row, on the organization's enabled
  connection, inside its P5.4 conversation (thread). A supplied conversation id must match; nothing is imported.
- **Idempotent and append-only:** the same inputs return the same proposal; changed inputs append the next version.
  Staleness is computed on read from the input digest, so history is never rewritten.
- **No side effects:** no outbound record, job, send intent, consent, suppression, account fact, owner or
  opportunity is written. Only the proposal, its audit and (on reject) a review row.
"""

import hashlib
import json
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.accounts import management
from app.accounts import service as account_service
from app.auth.dependencies import Capability
from app.auth.service import Actor
from app.contacts.addresses import Keyring
from app.core.clock import Clock
from app.core.errors import Conflict, NotFound
from app.core.settings import Settings
from app.inbox import service as inbox
from app.inbox.models import InboxThread
from app.intent import service as intent
from app.replies import composer, knowledge
from app.replies.models import ReplyProposalReview, ReplyProposalRow
from app.whatsapp import content
from app.whatsapp.models import ProviderConnection, ProviderEventItem, ProviderInboundMessage

DISABLED = "reply proposals are disabled (HERMECIOUS_REPLY_PROPOSALS=off; the P6.1 intent gate is not verified)"


def _message(db: Session, org: uuid.UUID, message_id: uuid.UUID) -> tuple[ProviderInboundMessage, ProviderEventItem]:
    row = db.execute(
        select(ProviderInboundMessage, ProviderEventItem)
        .join(ProviderEventItem, ProviderEventItem.id == ProviderInboundMessage.event_item_id)
        .where(ProviderInboundMessage.organization_id == org, ProviderInboundMessage.id == message_id)
    ).first()
    if row is None:
        raise NotFound()
    return row[0], row[1]


def _thread(db: Session, m: ProviderInboundMessage, *, lock: bool = False) -> InboxThread | None:
    query = select(InboxThread).where(
        InboxThread.organization_id == m.organization_id,
        InboxThread.provider_connection_id == m.provider_connection_id,
        InboxThread.party_key_id == m.sender_key_id, InboxThread.party_digest == m.sender_digest,
    )  # fmt: skip
    return db.scalar(query.with_for_update() if lock else query)


def _inputs(
    db: Session, org: uuid.UUID, m: ProviderInboundMessage, item: ProviderEventItem, offer_id: uuid.UUID | None,
    keys: Keyring | None, now: datetime,
) -> tuple[composer.Inputs, str]:  # fmt: skip
    text, state = inbox.message_text(m, item, keys, now)
    observation = intent.views(db, org, [m.id]).get(m.id)
    snap = knowledge.snapshot(db, org, offer_id, now)
    inputs = composer.Inputs(str(m.id), text, state, observation, snap, m.contact_id is not None, now)
    digest = hashlib.sha256(json.dumps({
        "message": str(m.id), "state": state, "text": hashlib.sha256((text or "").encode()).hexdigest(),
        "observation": observation["observation_id"] if observation else None,
        "classifier": observation["classifier_version"] if observation else None,
        "knowledge": snap.claims_digest, "contact": m.contact_id is not None,
        "composer": composer.COMPOSER_VERSION, "policy": composer.POLICY_VERSION,
    }, sort_keys=True).encode()).hexdigest()  # fmt: skip
    return inputs, digest


def _default_offer(db: Session, org: uuid.UUID, offer_id: uuid.UUID | None) -> uuid.UUID | None:
    if offer_id is not None:
        return offer_id
    published = knowledge.published_offers(db, org)
    return published[0] if len(published) == 1 else None  # ambiguous choice: no knowledge, so nothing asserted


def generate(
    db: Session, *, actor: Actor, clock: Clock, settings: Settings, message_id: uuid.UUID,
    offer_id: uuid.UUID | None, conversation_id: uuid.UUID | None,
) -> tuple[ReplyProposalRow, bool]:  # fmt: skip
    """Owner/operator: the proposal for this message's current inputs (existing one if unchanged). (row, created)."""
    account_service._require(actor, Capability.MUTATE)
    if settings.reply_proposals == "off" or (settings.reply_proposals == "fixtures"
                                              and settings.environment == "production"):  # fmt: skip
        raise Conflict(DISABLED)
    org, now = actor.organization_id, clock.now()
    m, item = _message(db, org, message_id)
    connection = db.scalar(select(ProviderConnection).where(ProviderConnection.organization_id == org))
    if connection is None or connection.id != m.provider_connection_id or not connection.enabled:
        raise Conflict("the message is not on this organization's enabled WhatsApp connection")
    thread = _thread(db, m, lock=True)  # serializes versions per conversation
    if thread is None or (conversation_id is not None and conversation_id != thread.id):
        raise Conflict("the message does not belong to this conversation")
    offer = _default_offer(db, org, offer_id)
    inputs, digest = _inputs(db, org, m, item, offer, content.keyring(settings), now)
    existing = db.scalar(
        select(ReplyProposalRow).where(
            ReplyProposalRow.organization_id == org, ReplyProposalRow.inbound_message_id == m.id,
            ReplyProposalRow.input_digest == digest,
        )
    )  # fmt: skip
    if existing is not None:
        db.rollback()
        return existing, False
    proposal = composer.propose(inputs)
    seq = int(db.scalar(select(func.coalesce(func.max(ReplyProposalRow.lineage_seq), 0)).where(
        ReplyProposalRow.inbound_message_id == m.id)) or 0) + 1  # fmt: skip
    row_id = db.scalar(
        insert(ReplyProposalRow)
        .values(
            id=uuid.uuid4(), organization_id=org, inbound_message_id=m.id, thread_id=thread.id,
            intent_observation_id=uuid.UUID(proposal.intent_observation_id) if proposal.intent_observation_id else None,
            offer_id=uuid.UUID(inputs.knowledge.offer_id) if inputs.knowledge.offer_id else None,
            offer_revision=inputs.knowledge.revision, input_digest=digest, lineage_seq=seq,
            schema_version=proposal.schema_version, status=proposal.status,
            recommended_action=proposal.recommended_action, proposal_json=proposal.model_dump(mode="json"),
            composer_version=proposal.composer_version, policy_version=proposal.policy_version,
            requested_by=actor.user_id, created_at=now,
        )
        .on_conflict_do_nothing(constraint="uq_reply_proposals_input")
        .returning(ReplyProposalRow.id)
    )  # fmt: skip
    if row_id is None:  # pragma: no cover  # the thread lock serializes this; kept for safety
        db.rollback()
        return generate(db, actor=actor, clock=clock, settings=settings, message_id=message_id, offer_id=offer_id,
                        conversation_id=conversation_id)  # fmt: skip
    management._audit(db, actor, clock, "reply.proposed", row_id,
                      {"status": proposal.status, "action": proposal.recommended_action, "version": seq,
                       "codes": list(proposal.abstention_codes), "citations": len(proposal.citations)},
                      target_type="reply_proposal")  # fmt: skip
    db.commit()
    row = db.get(ReplyProposalRow, row_id)
    assert row is not None  # noqa: S101
    return row, True


def views(
    db: Session, org: uuid.UUID, message_ids: list[uuid.UUID], keys: Keyring | None, now: datetime
) -> dict[uuid.UUID, list[dict[str, Any]]]:
    """Every proposal per message, newest first, each marked `stale` (inputs changed) or `superseded`."""
    if not message_ids:
        return {}
    rows = list(db.scalars(
        select(ReplyProposalRow)
        .where(ReplyProposalRow.organization_id == org, ReplyProposalRow.inbound_message_id.in_(message_ids))
        .order_by(ReplyProposalRow.inbound_message_id, ReplyProposalRow.lineage_seq.desc())
    ))  # fmt: skip
    if not rows:
        return {}
    rejected = {
        r.proposal_id: r for r in db.scalars(
            select(ReplyProposalReview).where(ReplyProposalReview.proposal_id.in_([p.id for p in rows]))
        )
    }  # fmt: skip
    current: dict[tuple[uuid.UUID, uuid.UUID | None], str] = {}
    out: dict[uuid.UUID, list[dict[str, Any]]] = {}
    for row in rows:
        key = (row.inbound_message_id, row.offer_id)
        if key not in current:
            m, item = _message(db, org, row.inbound_message_id)
            current[key] = _inputs(db, org, m, item, row.offer_id, keys, now)[1]
        lineage = out.setdefault(row.inbound_message_id, [])
        review = rejected.get(row.id)
        lineage.append({
            "id": str(row.id), "version": row.lineage_seq, "proposal": row.proposal_json,
            "stale": row.input_digest != current[key], "superseded": bool(lineage),
            "rejected": {"reason": review.reason, "at": review.reviewed_at.isoformat()} if review else None,
            "created_at": row.created_at.isoformat(), "sent": False, "label": "DRAFT — NOT SENT",
        })  # fmt: skip
    return out


def reject(
    db: Session, *, actor: Actor, clock: Clock, message_id: uuid.UUID, proposal_id: uuid.UUID, reason: str
) -> ReplyProposalReview:
    account_service._require(actor, Capability.MUTATE)
    org = actor.organization_id
    proposal = db.scalar(
        select(ReplyProposalRow).where(
            ReplyProposalRow.organization_id == org, ReplyProposalRow.id == proposal_id,
            ReplyProposalRow.inbound_message_id == message_id,
        ).with_for_update()
    )  # fmt: skip
    if proposal is None:
        raise NotFound()
    if db.scalar(select(ReplyProposalReview.id).where(ReplyProposalReview.proposal_id == proposal.id)):
        db.rollback()
        raise Conflict("this proposal was already rejected")
    review = ReplyProposalReview(organization_id=org, proposal_id=proposal.id, decision="rejected",
                                 reason=" ".join(reason.split())[:500], reviewer_id=actor.user_id,
                                 reviewed_at=clock.now())  # fmt: skip
    db.add(review)
    db.flush()
    management._audit(db, actor, clock, "reply.rejected", proposal.id, {"version": proposal.lineage_seq},
                      target_type="reply_proposal")  # fmt: skip
    db.commit()
    return review
