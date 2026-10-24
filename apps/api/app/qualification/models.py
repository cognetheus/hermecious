"""Account assessments (P3.3, ADR-018): append-only revisions; overrides are new revisions, never edits."""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
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

LEVELS = "'strong', 'moderate', 'weak', 'unknown'"


class Assessment(Base):
    __tablename__ = "assessments"
    __table_args__ = (
        UniqueConstraint("organization_id", "id"),
        UniqueConstraint("organization_id", "account_id", "revision", name="uq_assessments_account_revision"),
        ForeignKeyConstraint(
            ["organization_id", "account_id"], ["accounts.organization_id", "accounts.id"],
            name="fk_assessments_org_account",
        ),
        ForeignKeyConstraint(
            ["organization_id", "signal_snapshot_id"],
            ["school_signal_snapshots.organization_id", "school_signal_snapshots.id"],
            name="fk_assessments_org_snapshot",
        ),
        ForeignKeyConstraint(
            ["organization_id", "offer_id"], ["offers.organization_id", "offers.id"], name="fk_assessments_org_offer"
        ),
        ForeignKeyConstraint(
            ["organization_id", "supersedes_id"], ["assessments.organization_id", "assessments.id"],
            name="fk_assessments_org_supersedes",
        ),
        ForeignKeyConstraint(
            ["organization_id", "created_by"], ["users.organization_id", "users.id"], name="fk_assessments_org_creator"
        ),
        CheckConstraint("origin IN ('rubric', 'override')", name="origin"),
        CheckConstraint(f"customer_fit IN ({LEVELS}) AND need_evidence IN ({LEVELS}) AND accessibility IN ({LEVELS})"
                        f" AND delivery_fit IN ({LEVELS})", name="levels"),
        CheckConstraint("decision IN ('contact_now', 'investigate', 'nurture', 'exclude')", name="decision"),
        CheckConstraint("channel_eligibility = 'not_evaluated'", name="channel_not_evaluated"),
        CheckConstraint("revision >= 1", name="revision_positive"),
        CheckConstraint("input_digest ~ '^[0-9a-f]{64}$'", name="input_digest_format"),
        CheckConstraint("(origin = 'override') = (override_reason IS NOT NULL)", name="override_has_reason"),
        CheckConstraint("override_reason IS NULL OR char_length(override_reason) BETWEEN 3 AND 1000",
                        name="override_reason_length"),
    )  # fmt: skip

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"))
    account_id: Mapped[uuid.UUID]
    revision: Mapped[int] = mapped_column(Integer)
    origin: Mapped[str] = mapped_column(String(16))
    rubric_version: Mapped[str] = mapped_column(String(40))
    input_digest: Mapped[str] = mapped_column(String(64))
    signal_snapshot_id: Mapped[uuid.UUID]
    offer_id: Mapped[uuid.UUID | None]
    offer_revision_id: Mapped[uuid.UUID | None]
    capability_version: Mapped[str | None] = mapped_column(String(80))
    customer_fit: Mapped[str] = mapped_column(String(16))
    need_evidence: Mapped[str] = mapped_column(String(16))
    accessibility: Mapped[str] = mapped_column(String(16))
    delivery_fit: Mapped[str] = mapped_column(String(16))
    decision: Mapped[str] = mapped_column(String(16))
    channel_eligibility: Mapped[str] = mapped_column(String(16))
    explanation_json: Mapped[dict[str, Any]] = mapped_column(JSONB)  # the machine explanation, kept on overrides
    questions_json: Mapped[list[str]] = mapped_column(JSONB)
    supersedes_id: Mapped[uuid.UUID | None]
    override_reason: Mapped[str | None] = mapped_column(Text)
    override_evidence_ids: Mapped[list[str]] = mapped_column(JSONB)
    changed_fields: Mapped[list[str]] = mapped_column(JSONB)
    created_by: Mapped[uuid.UUID]
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
