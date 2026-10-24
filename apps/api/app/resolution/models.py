"""Campus identity review state (P2.3, ADR-014).

`identity_suggestions`: one row per canonical pair and algorithm version.
`identity_decisions`: append-only log of every human decision.
`candidate_account_links`: reviewed candidate→account associations. A link is
ended, never deleted. Nothing here deletes or rewrites candidates, sources,
accounts or facts.
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
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.persistence.base import Base

SUGGESTION_STATUSES = ("pending", "confirmed", "distinct", "deferred", "superseded", "undone", "reallocation_review")
ACTIONS = ("confirm_same_campus", "mark_distinct", "defer", "undo")


def _in(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{v}'" for v in values)


class IdentitySuggestion(Base):
    __tablename__ = "identity_suggestions"
    __table_args__ = (
        UniqueConstraint("organization_id", "id"),
        ForeignKeyConstraint(
            ["organization_id", "left_candidate_id"],
            ["discovery_candidates.organization_id", "discovery_candidates.id"],
            name="fk_identity_suggestions_org_left",
        ),
        ForeignKeyConstraint(
            ["organization_id", "right_candidate_id"],
            ["discovery_candidates.organization_id", "discovery_candidates.id"],
            name="fk_identity_suggestions_org_right",
        ),
        ForeignKeyConstraint(
            ["organization_id", "existing_account_id"],
            ["accounts.organization_id", "accounts.id"],
            name="fk_identity_suggestions_org_account",
        ),
        ForeignKeyConstraint(
            ["organization_id", "reviewer_user_id"],
            ["users.organization_id", "users.id"],
            name="fk_identity_suggestions_org_reviewer",
        ),
        CheckConstraint(
            "(right_candidate_id IS NULL) <> (existing_account_id IS NULL)", name="exactly_one_counterpart"
        ),
        CheckConstraint("right_candidate_id IS NULL OR left_candidate_id < right_candidate_id", name="canonical_order"),
        CheckConstraint("resolution IN ('suggest_review', 'insufficient_evidence')", name="resolution"),
        CheckConstraint(f"status IN ({_in(SUGGESTION_STATUSES)})", name="status"),
        CheckConstraint("version >= 1", name="version_positive"),
        Index(
            "uq_identity_suggestions_candidate_pair",
            "organization_id",
            "left_candidate_id",
            "right_candidate_id",
            "algorithm_version",
            unique=True,
            postgresql_where=text("right_candidate_id IS NOT NULL"),
        ),
        Index(
            "uq_identity_suggestions_candidate_account",
            "organization_id",
            "left_candidate_id",
            "existing_account_id",
            "algorithm_version",
            unique=True,
            postgresql_where=text("existing_account_id IS NOT NULL"),
        ),
        Index("ix_identity_suggestions_org_status_created", "organization_id", "status", "created_at", "id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"))
    left_candidate_id: Mapped[uuid.UUID]
    right_candidate_id: Mapped[uuid.UUID | None]
    existing_account_id: Mapped[uuid.UUID | None]
    algorithm_version: Mapped[str] = mapped_column(String(40))
    resolution: Mapped[str] = mapped_column(String(32))
    reason_codes: Mapped[list[str]] = mapped_column(JSONB)
    features: Mapped[dict[str, Any]] = mapped_column(JSONB)
    evidence_source_record_ids: Mapped[list[str]] = mapped_column(JSONB)
    left_revision: Mapped[int] = mapped_column(Integer)
    right_revision: Mapped[int | None] = mapped_column(Integer)
    evidence_changed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(24))
    version: Mapped[int] = mapped_column(Integer)
    reviewer_user_id: Mapped[uuid.UUID | None]
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    decision_reason: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class CandidateAccountLink(Base):
    __tablename__ = "candidate_account_links"
    __table_args__ = (
        UniqueConstraint("organization_id", "id"),
        ForeignKeyConstraint(
            ["organization_id", "candidate_id"],
            ["discovery_candidates.organization_id", "discovery_candidates.id"],
            name="fk_candidate_account_links_org_candidate",
        ),
        ForeignKeyConstraint(
            ["organization_id", "account_id"],
            ["accounts.organization_id", "accounts.id"],
            name="fk_candidate_account_links_org_account",
        ),
        ForeignKeyConstraint(
            ["organization_id", "suggestion_id"],
            ["identity_suggestions.organization_id", "identity_suggestions.id"],
            name="fk_candidate_account_links_org_suggestion",
        ),
        ForeignKeyConstraint(
            ["organization_id", "linked_by"], ["users.organization_id", "users.id"], name="fk_cal_org_linked_by"
        ),
        ForeignKeyConstraint(
            ["organization_id", "unlinked_by"], ["users.organization_id", "users.id"], name="fk_cal_org_unlinked_by"
        ),
        CheckConstraint("(unlinked_at IS NULL) = (unlinked_by IS NULL)", name="unlink_complete"),
        # At most one active account per candidate; ended links stay as history.
        Index(
            "uq_candidate_account_links_active",
            "organization_id",
            "candidate_id",
            unique=True,
            postgresql_where=text("unlinked_at IS NULL"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"))
    candidate_id: Mapped[uuid.UUID]
    account_id: Mapped[uuid.UUID]
    suggestion_id: Mapped[uuid.UUID | None]
    linked_by: Mapped[uuid.UUID]
    linked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    unlinked_by: Mapped[uuid.UUID | None]
    unlinked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class IdentityDecision(Base):
    """Append-only (database trigger): every review command, its effect and what it reverses."""

    __tablename__ = "identity_decisions"
    __table_args__ = (
        UniqueConstraint("organization_id", "command_id"),
        UniqueConstraint("organization_id", "id"),
        ForeignKeyConstraint(
            ["organization_id", "suggestion_id"],
            ["identity_suggestions.organization_id", "identity_suggestions.id"],
            name="fk_identity_decisions_org_suggestion",
        ),
        ForeignKeyConstraint(
            ["organization_id", "actor_user_id"],
            ["users.organization_id", "users.id"],
            name="fk_identity_decisions_org_actor",
        ),
        ForeignKeyConstraint(
            ["organization_id", "reverses_decision_id"],
            ["identity_decisions.organization_id", "identity_decisions.id"],
            name="fk_identity_decisions_org_reverses",
        ),
        CheckConstraint(f"action IN ({_in(ACTIONS)})", name="action"),
        CheckConstraint("char_length(reason) BETWEEN 3 AND 1000", name="reason_length"),
        CheckConstraint("payload_digest ~ '^[0-9a-f]{64}$'", name="payload_digest_format"),
        Index("ix_identity_decisions_org_suggestion", "organization_id", "suggestion_id", "recorded_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"))
    suggestion_id: Mapped[uuid.UUID]
    command_id: Mapped[uuid.UUID]
    action: Mapped[str] = mapped_column(String(32))
    actor_user_id: Mapped[uuid.UUID]
    prior_status: Mapped[str] = mapped_column(String(24))
    next_status: Mapped[str] = mapped_column(String(24))
    expected_version: Mapped[int] = mapped_column(Integer)
    reason: Mapped[str] = mapped_column(Text)
    payload_digest: Mapped[str] = mapped_column(String(64))
    held_fact_ids: Mapped[list[str]] = mapped_column(JSONB)
    link_id: Mapped[uuid.UUID | None]
    reverses_decision_id: Mapped[uuid.UUID | None]
    request_id: Mapped[str | None] = mapped_column(String(64))
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
