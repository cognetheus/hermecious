"""Immutable first-contact draft revisions (P4.2, ADR-021). Append-only; never sendable."""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.persistence.base import Base


class Draft(Base):
    __tablename__ = "drafts"
    __table_args__ = (
        UniqueConstraint("organization_id", "id"),
        UniqueConstraint("organization_id", "idempotency_key", name="uq_drafts_idempotency"),
        UniqueConstraint("organization_id", "campaign_id", "account_id", "revision", name="uq_drafts_revision"),
        ForeignKeyConstraint(
            ["organization_id", "campaign_id"],
            ["campaigns.organization_id", "campaigns.id"],
            name="fk_drafts_org_campaign",
        ),
        ForeignKeyConstraint(
            ["organization_id", "account_id"], ["accounts.organization_id", "accounts.id"], name="fk_drafts_org_account"
        ),
        ForeignKeyConstraint(
            ["organization_id", "membership_id"],
            ["campaign_accounts.organization_id", "campaign_accounts.id"],
            name="fk_drafts_org_membership",
        ),
        ForeignKeyConstraint(
            ["organization_id", "assessment_id"],
            ["assessments.organization_id", "assessments.id"],
            name="fk_drafts_org_assessment",
        ),
        ForeignKeyConstraint(
            ["organization_id", "regenerated_from"],
            ["drafts.organization_id", "drafts.id"],
            name="fk_drafts_org_previous",
        ),
        ForeignKeyConstraint(
            ["organization_id", "created_by"], ["users.organization_id", "users.id"], name="fk_drafts_org_creator"
        ),
        CheckConstraint("status = 'needs_review'", name="stored_status"),
        CheckConstraint("operator_review_required", name="review_required"),
        CheckConstraint("NOT sendable", name="never_sendable"),
        CheckConstraint("channel_eligibility = 'not_evaluated'", name="channel_not_evaluated"),
        CheckConstraint("char_length(body_text) <= 650", name="body_length"),
        CheckConstraint("origin IN ('generated', 'edited')", name="origin"),
        CheckConstraint("fingerprint ~ '^[0-9a-f]{64}$'", name="fingerprint_format"),
        CheckConstraint("request_digest ~ '^[0-9a-f]{64}$'", name="request_digest_format"),
        CheckConstraint("(regenerated_from IS NULL) = (regenerate_reason IS NULL)", name="regeneration_reason"),
        CheckConstraint("revision >= 1", name="revision_positive"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"))
    campaign_id: Mapped[uuid.UUID]
    account_id: Mapped[uuid.UUID]
    membership_id: Mapped[uuid.UUID]
    revision: Mapped[int] = mapped_column(Integer)
    mode: Mapped[str] = mapped_column(String(16))
    template_id: Mapped[str] = mapped_column(String(60))
    locale: Mapped[str] = mapped_column(String(16))
    contract_version: Mapped[str] = mapped_column(String(40))
    body_text: Mapped[str] = mapped_column(Text)
    sentences_json: Mapped[list[dict[str, Any]]] = mapped_column(JSONB)
    assessment_id: Mapped[uuid.UUID]
    assessment_revision: Mapped[int] = mapped_column(Integer)
    offer_id: Mapped[uuid.UUID]
    offer_revision_id: Mapped[uuid.UUID]
    capability_version: Mapped[str] = mapped_column(String(80))
    signal_snapshot_id: Mapped[uuid.UUID | None]
    fact_ids: Mapped[list[str]] = mapped_column(JSONB)
    source_policy_versions: Mapped[list[str]] = mapped_column(JSONB)
    fingerprint: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(16))
    operator_review_required: Mapped[bool] = mapped_column(Boolean)
    sendable: Mapped[bool] = mapped_column(Boolean)
    channel_eligibility: Mapped[str] = mapped_column(String(16))
    idempotency_key: Mapped[str] = mapped_column(String(100))
    request_digest: Mapped[str] = mapped_column(String(64))
    regenerated_from: Mapped[uuid.UUID | None]
    regenerate_reason: Mapped[str | None] = mapped_column(Text)
    origin: Mapped[str] = mapped_column(String(16), server_default="generated")
    created_by: Mapped[uuid.UUID]
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
