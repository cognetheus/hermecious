"""Offer catalog (P1.3): offers and immutable, versioned offer revisions.

A revision's content never changes after insert (enforced by a Postgres
trigger, migration 0004); edits create a new revision. Contract:
docs/contracts/offer-catalog.md.
"""

import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, ForeignKeyConstraint, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.persistence.base import Base


class OfferStatus(StrEnum):
    DRAFT = "draft"
    PUBLISHED = "published"
    ARCHIVED = "archived"


class RevisionState(StrEnum):
    DRAFT = "draft"
    PUBLISHED = "published"
    RETIRED = "retired"


class Offer(Base):
    __tablename__ = "offers"
    __table_args__ = (
        UniqueConstraint("organization_id", "code"),
        UniqueConstraint("organization_id", "id"),
        CheckConstraint("status IN ('draft', 'published', 'archived')", name="status"),
        CheckConstraint("code ~ '^[a-z][a-z0-9_]{2,99}$'", name="code_format"),
        CheckConstraint("version >= 1", name="version_positive"),
        CheckConstraint("status <> 'published' OR published_revision_id IS NOT NULL", name="published_has_revision"),
        # Revision pointers stay inside the organization; created after offer_revisions (cycle).
        ForeignKeyConstraint(
            ["organization_id", "current_draft_revision_id"],
            ["offer_revisions.organization_id", "offer_revisions.id"],
            name="fk_offers_org_current_draft",
            use_alter=True,
        ),
        ForeignKeyConstraint(
            ["organization_id", "published_revision_id"],
            ["offer_revisions.organization_id", "offer_revisions.id"],
            name="fk_offers_org_published",
            use_alter=True,
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"))
    vertical_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("verticals.id"))
    code: Mapped[str] = mapped_column(String(100))
    audience: Mapped[str] = mapped_column(String(200))
    current_draft_revision_id: Mapped[uuid.UUID | None]
    published_revision_id: Mapped[uuid.UUID | None]
    status: Mapped[str] = mapped_column(String(16))
    version: Mapped[int] = mapped_column(Integer, server_default="1")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class OfferRevision(Base):
    __tablename__ = "offer_revisions"
    __table_args__ = (
        UniqueConstraint("organization_id", "offer_id", "revision"),
        UniqueConstraint("organization_id", "id"),
        ForeignKeyConstraint(
            ["organization_id", "offer_id"],
            ["offers.organization_id", "offers.id"],
            name="fk_offer_revisions_org_offer",
        ),
        ForeignKeyConstraint(
            ["organization_id", "created_by"],
            ["users.organization_id", "users.id"],
            name="fk_offer_revisions_org_creator",
        ),
        ForeignKeyConstraint(
            ["organization_id", "approved_by"],
            ["users.organization_id", "users.id"],
            name="fk_offer_revisions_org_approver",
        ),
        CheckConstraint("state IN ('draft', 'published', 'retired')", name="state"),
        CheckConstraint("revision >= 1", name="revision_positive"),
        CheckConstraint("content_sha256 ~ '^[0-9a-f]{64}$'", name="content_sha256_format"),
        CheckConstraint(
            "state = 'draft' OR (approved_by IS NOT NULL AND approved_at IS NOT NULL AND published_at IS NOT NULL)"
            " OR (state = 'retired' AND published_at IS NULL)",
            name="published_has_approval",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"))
    offer_id: Mapped[uuid.UUID]
    revision: Mapped[int] = mapped_column(Integer)
    state: Mapped[str] = mapped_column(String(16))
    capability_version: Mapped[str] = mapped_column(String(80))
    approved_claims_json: Mapped[list[dict[str, Any]]] = mapped_column(JSONB)
    capability_matrix_json: Mapped[list[dict[str, Any]]] = mapped_column(JSONB)
    price_rules_json: Mapped[list[dict[str, Any]]] = mapped_column(JSONB)
    exclusions_json: Mapped[list[str]] = mapped_column(JSONB)
    dependencies_json: Mapped[list[str]] = mapped_column(JSONB)
    evidence_references_json: Mapped[list[dict[str, Any]]] = mapped_column(JSONB)
    created_by: Mapped[uuid.UUID]
    approved_by: Mapped[uuid.UUID | None]
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    content_sha256: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
