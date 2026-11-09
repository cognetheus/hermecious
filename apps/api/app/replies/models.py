"""Stored reply proposals and their reviews (P6.2, ADR-032). Both append-only.

A proposal is never edited, approved or sent. A new version is appended when an input changes; whether a stored
proposal is still current is computed on read from its input digest, so nothing ever rewrites history.
"""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.persistence.base import Base


def _org_fk(cols: list[str], target: str, name: str) -> ForeignKeyConstraint:
    return ForeignKeyConstraint(["organization_id", *cols], [f"{target}.organization_id", f"{target}.id"], name=name)


class ReplyProposalRow(Base):
    __tablename__ = "reply_proposals"
    __table_args__ = (
        UniqueConstraint("organization_id", "id"),
        UniqueConstraint("organization_id", "inbound_message_id", "input_digest", name="uq_reply_proposals_input"),
        UniqueConstraint("inbound_message_id", "lineage_seq", name="uq_reply_proposals_lineage"),
        _org_fk(["inbound_message_id"], "provider_inbound_messages", "fk_reply_proposals_org_message"),
        _org_fk(["thread_id"], "inbox_threads", "fk_reply_proposals_org_thread"),
        _org_fk(["intent_observation_id"], "intent_observations", "fk_reply_proposals_org_observation"),
        _org_fk(["offer_id"], "offers", "fk_reply_proposals_org_offer"),
        CheckConstraint("status IN ('proposed', 'abstained')", name="status"),
        CheckConstraint("schema_version = 'reply.v1'", name="schema_version"),
        CheckConstraint("input_digest ~ '^[0-9a-f]{64}$'", name="input_digest_format"),
        CheckConstraint("lineage_seq >= 1", name="lineage_seq_positive"),
        Index("ix_reply_proposals_message", "inbound_message_id", "lineage_seq"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"))
    inbound_message_id: Mapped[uuid.UUID]
    thread_id: Mapped[uuid.UUID]
    intent_observation_id: Mapped[uuid.UUID | None]
    offer_id: Mapped[uuid.UUID | None]
    offer_revision: Mapped[int | None] = mapped_column(Integer)
    input_digest: Mapped[str] = mapped_column(String(64))
    lineage_seq: Mapped[int] = mapped_column(Integer)
    schema_version: Mapped[str] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(16))
    recommended_action: Mapped[str] = mapped_column(String(40))
    proposal_json: Mapped[dict[str, Any]] = mapped_column(JSONB)
    composer_version: Mapped[str] = mapped_column(String(40))
    policy_version: Mapped[str] = mapped_column(String(40))
    requested_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ReplyProposalReview(Base):
    __tablename__ = "reply_proposal_reviews"
    __table_args__ = (
        UniqueConstraint("organization_id", "id"),
        _org_fk(["proposal_id"], "reply_proposals", "fk_reply_proposal_reviews_org_proposal"),
        CheckConstraint("decision = 'rejected'", name="decision"),
        CheckConstraint("char_length(reason) BETWEEN 3 AND 500", name="reason_length"),
        Index("ix_reply_proposal_reviews_proposal", "proposal_id", "reviewed_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"))
    proposal_id: Mapped[uuid.UUID]
    decision: Mapped[str] = mapped_column(String(16))
    reason: Mapped[str] = mapped_column(Text)
    reviewer_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    reviewed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
