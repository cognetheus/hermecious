"""Intent observations for signed inbound WhatsApp messages (P6.1, ADR-031). Never sends, suppresses or grants.

- **Source:** only `provider_inbound_messages`, the signed P5.2 facts. P5.3 test sends, P4.5 simulated items,
  unmapped webhooks and other organizations are never classified.
- **Writing:** classification runs in the P5.2 processor's transaction, inside a savepoint. A classifier fault
  never loses the signed message; the `intent.classify` backfill retries later. Observations are append-only and
  unique per (message, classifier version, source revision), so retries add nothing and a new version appends.
- **Reviews:** an operator confirms or corrects an observation. The review is stored separately, audited, and
  changes nothing else: not the observation, not the classifier, not consent or suppression.
"""

import hashlib
import logging
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.accounts import management
from app.accounts import service as account_service
from app.auth.dependencies import Capability
from app.auth.service import Actor
from app.contacts.addresses import Keyring
from app.core.clock import Clock
from app.core.errors import Conflict, NotFound, Unprocessable
from app.inbox import service as inbox
from app.intent import classifier
from app.intent.models import PRIMARY, IntentObservationRow, IntentReview
from app.jobs import registry as job_registry
from app.jobs import service as job_service
from app.whatsapp.models import ProviderConnection, ProviderEventItem, ProviderInboundMessage

logger = logging.getLogger("app.intent")
BATCH = 200


def _revision(text: str | None, state: str) -> str:
    return hashlib.sha256(f"{state}:{text or ''}".encode()).hexdigest()


def record(
    db: Session, message: ProviderInboundMessage, item: ProviderEventItem, keys: Keyring | None, now: datetime
) -> None:
    """Classify one signed inbound message and append its observation (no-op if this version already has it)."""
    text, state = inbox.message_text(message, item, keys, now)
    observation = classifier.observe(text or "", message_id=str(message.id), now=now, content_state=state)
    db.execute(
        insert(IntentObservationRow)
        .values(
            id=uuid.uuid4(), organization_id=message.organization_id, inbound_message_id=message.id,
            schema_version=observation.schema_version, classifier_version=observation.classifier_version,
            source_revision=_revision(text, state), primary_intent=observation.primary_intent,
            requires_human_review=observation.requires_human_review,
            result_json=observation.model_dump(mode="json"), created_at=now,
        )
        .on_conflict_do_nothing(constraint="uq_intent_observations_version")
    )  # fmt: skip


def record_safely(
    db: Session, message_id: uuid.UUID, item: ProviderEventItem, keys: Keyring | None, now: datetime
) -> None:
    """Called by the P5.2 processor. A fault rolls back only the savepoint; the signed message is never lost."""
    try:
        with db.begin_nested():
            message = db.get(ProviderInboundMessage, message_id)
            if message is not None:
                record(db, message, item, keys, now)
    except Exception:
        logger.exception("intent.classify_failed", extra={"context": {"message_id": str(message_id)}})


def backfill(
    db: Session, org: uuid.UUID, connection_id: uuid.UUID, keys: Keyring | None, now: datetime,
    ctx: job_registry.JobContext | None = None,
) -> dict[str, int]:  # fmt: skip
    """Classify every signed inbound message that has no observation for the current classifier version."""
    done = 0
    while True:
        if ctx is not None:
            job_registry.keep_alive(ctx)
        classified = select(IntentObservationRow.inbound_message_id).where(
            IntentObservationRow.organization_id == org,
            IntentObservationRow.classifier_version == classifier.CLASSIFIER_VERSION,
        )
        rows = db.execute(
            select(ProviderInboundMessage, ProviderEventItem)
            .join(ProviderEventItem, ProviderEventItem.id == ProviderInboundMessage.event_item_id)
            .where(ProviderInboundMessage.organization_id == org,
                   ProviderInboundMessage.provider_connection_id == connection_id,
                   ProviderInboundMessage.id.not_in(classified))
            .order_by(ProviderEventItem.arrival_seq)
            .limit(BATCH)
        ).all()  # fmt: skip
        if not rows:
            return {"classified": done}
        for message, item in rows:
            record(db, message, item, keys, now)
        db.commit()
        done += len(rows)


def request_backfill(db: Session, *, actor: Actor, clock: Clock, environment: str) -> uuid.UUID:
    account_service._require(actor, Capability.ADMINISTER)
    connection = db.scalar(
        select(ProviderConnection).where(ProviderConnection.organization_id == actor.organization_id)
    )
    if connection is None:
        raise NotFound()
    now = clock.now()
    receipt = job_service.enqueue_job(
        db, organization_id=actor.organization_id, environment=environment, job_type="intent.classify",
        schema_version=1, payload={"connection_id": str(connection.id)},
        idempotency_key=f"intent.classify.{connection.id}.{classifier.CLASSIFIER_VERSION}.{int(now.timestamp())}",
        clock=clock,
    )  # fmt: skip
    management._audit(db, actor, clock, "intent.backfill_requested", connection.id,
                      {"classifier_version": classifier.CLASSIFIER_VERSION, "job_id": str(receipt.job_id)},
                      target_type="provider_connection")  # fmt: skip
    db.commit()
    return receipt.job_id


# --- reads ---------------------------------------------------------------------------------------------------------


def views(db: Session, org: uuid.UUID, message_ids: list[uuid.UUID]) -> dict[uuid.UUID, dict[str, Any]]:
    """The newest observation for the current classifier version, per message, with its newest review."""
    if not message_ids:
        return {}
    rows = db.scalars(
        select(IntentObservationRow)
        .where(IntentObservationRow.organization_id == org, IntentObservationRow.inbound_message_id.in_(message_ids),
               IntentObservationRow.classifier_version == classifier.CLASSIFIER_VERSION)
        .order_by(IntentObservationRow.created_at, IntentObservationRow.id)
    )  # fmt: skip
    latest: dict[uuid.UUID, IntentObservationRow] = {}
    for row in rows:
        latest[row.inbound_message_id] = row
    reviews: dict[uuid.UUID, IntentReview] = {}
    if latest:
        for item in db.scalars(
            select(IntentReview)
            .where(IntentReview.organization_id == org,
                   IntentReview.observation_id.in_([r.id for r in latest.values()]))
            .order_by(IntentReview.reviewed_at, IntentReview.id)
        ):  # fmt: skip
            reviews[item.observation_id] = item
    out = {}
    for message_id, row in latest.items():
        latest_review = reviews.get(row.id)
        out[message_id] = row.result_json | {
            "observation_id": str(row.id),
            "review": {"decision": latest_review.decision, "corrected_primary": latest_review.corrected_primary,
                       "note": latest_review.note, "reviewed_at": latest_review.reviewed_at.isoformat()}
            if latest_review else None,
            "notice": "For human review only. Not a prediction of a sale and not an action.",
        }  # fmt: skip
    return out


# --- the operator's review -----------------------------------------------------------------------------------------


def review(
    db: Session, *, actor: Actor, clock: Clock, message_id: uuid.UUID, observation_id: uuid.UUID, decision: str,
    corrected_primary: str | None, note: str,
) -> IntentReview:  # fmt: skip
    """Owner/operator: confirm or correct an observation. Audited; it changes nothing else."""
    account_service._require(actor, Capability.MUTATE)
    org = actor.organization_id
    observation = db.scalar(
        select(IntentObservationRow).where(
            IntentObservationRow.organization_id == org, IntentObservationRow.id == observation_id,
            IntentObservationRow.inbound_message_id == message_id,
        )
    )  # fmt: skip
    if observation is None:
        raise NotFound()
    if decision == "corrected" and corrected_primary not in PRIMARY:
        raise Unprocessable("CORRECTION_LABEL: choose one of the ten intents")
    if decision == "corrected" and corrected_primary == observation.primary_intent:
        raise Conflict("the correction repeats the classifier's label; confirm it instead")
    row = IntentReview(
        organization_id=org, observation_id=observation.id, decision=decision,
        corrected_primary=corrected_primary if decision == "corrected" else None, note=" ".join(note.split())[:500],
        reviewer_id=actor.user_id, reviewed_at=clock.now(),
    )  # fmt: skip
    db.add(row)
    db.flush()
    management._audit(db, actor, clock, "intent.reviewed", observation.id,
                      {"decision": decision, "classifier": observation.primary_intent,
                       "corrected_primary": row.corrected_primary}, target_type="intent_observation")  # fmt: skip
    db.commit()
    return row
