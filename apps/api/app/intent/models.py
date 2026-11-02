"""Stored intent observations and separate human reviews (P6.1, ADR-031). Both append-only.

An observation is unique per (organization, inbound message, classifier version, source revision): retries and
redeliveries add nothing, and a new classifier version appends a new observation without touching the signed source
or the old one. A review is the operator's own judgement, kept apart: it never changes the observation, the
classifier or any policy.
"""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.persistence.base import Base

PRIMARY = ("interested", "needs_details", "objection", "request_demo", "defer", "not_interested", "opt_out",
           "human_request", "ambiguous", "abusive")  # fmt: skip
_PRIMARY_SQL = ", ".join(f"'{p}'" for p in PRIMARY)


class IntentObservationRow(Base):
    __tablename__ = "intent_observations"
    __table_args__ = (
        UniqueConstraint("organization_id", "id"),
        UniqueConstraint(
            "organization_id",
            "inbound_message_id",
            "classifier_version",
            "source_revision",
            name="uq_intent_observations_version",
        ),  # fmt: skip
        ForeignKeyConstraint(
            ["organization_id", "inbound_message_id"],
            ["provider_inbound_messages.organization_id", "provider_inbound_messages.id"],
            name="fk_intent_observations_org_message",
        ),
        CheckConstraint(f"primary_intent IN ({_PRIMARY_SQL})", name="primary_intent"),
        CheckConstraint("schema_version = 'intent.v1'", name="schema_version"),
        CheckConstraint("source_revision ~ '^[0-9a-f]{64}$'", name="source_revision_format"),
        Index("ix_intent_observations_message", "inbound_message_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"))
    inbound_message_id: Mapped[uuid.UUID]
    schema_version: Mapped[str] = mapped_column(String(16))
    classifier_version: Mapped[str] = mapped_column(String(40))
    source_revision: Mapped[str] = mapped_column(String(64))
    primary_intent: Mapped[str] = mapped_column(String(24))
    requires_human_review: Mapped[bool] = mapped_column(Boolean)
    result_json: Mapped[dict[str, Any]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class IntentReview(Base):
    __tablename__ = "intent_reviews"
    __table_args__ = (
        UniqueConstraint("organization_id", "id"),
        ForeignKeyConstraint(
            ["organization_id", "observation_id"],
            ["intent_observations.organization_id", "intent_observations.id"],
            name="fk_intent_reviews_org_observation",
        ),
        CheckConstraint("decision IN ('confirmed', 'corrected')", name="decision"),
        CheckConstraint(
            f"(decision = 'corrected') = (corrected_primary IS NOT NULL) AND (corrected_primary IS NULL OR "
            f"corrected_primary IN ({_PRIMARY_SQL}))",
            name="correction_label",
        ),
        CheckConstraint("char_length(note) <= 500", name="note_length"),
        Index("ix_intent_reviews_observation", "observation_id", "reviewed_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"))
    observation_id: Mapped[uuid.UUID]
    decision: Mapped[str] = mapped_column(String(16))
    corrected_primary: Mapped[str | None] = mapped_column(String(24))
    note: Mapped[str] = mapped_column(Text)
    reviewer_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    reviewed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
