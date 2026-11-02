"""Production go/no-go and the operator-only pilot gate (P5.5, ADR-030).

- `ReadinessAssessment`: an immutable, digest-bound, expiring snapshot of every prerequisite, computed only from
  system evidence and owner attestations. It never grants anything by itself.
- `ReadinessAttestation`: an owner's recorded human decision (legal review, Meta business verification, ...) with an
  evidence reference; append-only and expiring. Never created by an agent, a job or a model.
- `PilotAuthorization`: a separate owner act: one connection, one purpose, a hard daily cap, an expiry; pausable and
  revocable.
- `PilotSend`: one owner-confirmed message to one opted-in contact for one exact approved draft revision. Reserved
  before the single Graph call; never resent.
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
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.persistence.base import Base

ASSESSMENT_STATUSES = ("no_go", "blocked_external", "ready_for_operator_review")
ATTESTATION_KINDS = (
    "meta_business_verification",
    "pakistan_legal_review",
    "real_test_receipt",
    "operations_readiness",
)
PILOT_STATES = ("awaiting_confirmation", "reserved", "provider_accepted", "definitively_rejected", "indeterminate",
                "denied", "expired", "cancelled")  # fmt: skip


def _org_fk(cols: list[str], target: str, name: str) -> ForeignKeyConstraint:
    return ForeignKeyConstraint(["organization_id", *cols], [f"{target}.organization_id", f"{target}.id"], name=name)


def _in(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{v}'" for v in values)


class ReadinessAttestation(Base):
    __tablename__ = "readiness_attestations"
    __table_args__ = (
        UniqueConstraint("organization_id", "id"),
        CheckConstraint(f"kind IN ({_in(ATTESTATION_KINDS)})", name="kind"),
        CheckConstraint("char_length(evidence_ref) BETWEEN 10 AND 500", name="evidence_ref_length"),
        CheckConstraint("char_length(statement) BETWEEN 20 AND 1000", name="statement_length"),
        CheckConstraint("expires_at > attested_at", name="expires_after"),
        Index("ix_readiness_attestations_kind", "organization_id", "kind", "attested_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"))
    kind: Mapped[str] = mapped_column(String(40))
    statement: Mapped[str] = mapped_column(Text)
    evidence_ref: Mapped[str] = mapped_column(String(500))
    attested_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    attested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ReadinessAssessment(Base):
    __tablename__ = "readiness_assessments"
    __table_args__ = (
        UniqueConstraint("organization_id", "id"),
        CheckConstraint(f"status IN ({_in(ASSESSMENT_STATUSES)})", name="status"),
        CheckConstraint("digest ~ '^[0-9a-f]{64}$'", name="digest_format"),
        CheckConstraint("expires_at > checked_at", name="expires_after"),
        Index("ix_readiness_assessments_recent", "organization_id", "checked_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"))
    snapshot_version: Mapped[str] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(32))
    digest: Mapped[str] = mapped_column(String(64))
    checks_json: Mapped[list[dict[str, Any]]] = mapped_column(JSONB)
    identity_json: Mapped[dict[str, Any]] = mapped_column(JSONB)  # fingerprints only, never raw IDs or secrets
    environment: Mapped[str] = mapped_column(String(16))
    build_sha: Mapped[str | None] = mapped_column(String(40))
    checked_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    checked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class PilotAuthorization(Base):
    __tablename__ = "pilot_authorizations"
    __table_args__ = (
        UniqueConstraint("organization_id", "id"),
        _org_fk(["provider_connection_id"], "provider_connections", "fk_pilot_authorizations_org_connection"),
        _org_fk(["assessment_id"], "readiness_assessments", "fk_pilot_authorizations_org_assessment"),
        CheckConstraint("status IN ('active', 'paused', 'revoked')", name="status"),
        CheckConstraint("purpose IN ('marketing', 'utility')", name="purpose"),
        CheckConstraint("max_per_day BETWEEN 1 AND 3", name="max_per_day_range"),
        CheckConstraint("expires_at > created_at", name="expires_after"),
        CheckConstraint("expires_at <= created_at + interval '14 days'", name="expires_within_14_days"),
        CheckConstraint("assessment_digest ~ '^[0-9a-f]{64}$'", name="assessment_digest_format"),
        Index(
            "uq_pilot_authorizations_live",
            "provider_connection_id",
            unique=True,
            postgresql_where=text("status IN ('active', 'paused')"),
        ),  # fmt: skip
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"))
    provider_connection_id: Mapped[uuid.UUID]
    assessment_id: Mapped[uuid.UUID]
    assessment_digest: Mapped[str] = mapped_column(String(64))
    purpose: Mapped[str] = mapped_column(String(16))
    max_per_day: Mapped[int] = mapped_column(Integer)
    acknowledgement: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16))
    pause_reason: Mapped[str | None] = mapped_column(String(40))
    authorized_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    version: Mapped[int] = mapped_column(Integer)


class PilotSend(Base):
    __tablename__ = "pilot_sends"
    __table_args__ = (
        UniqueConstraint("organization_id", "id"),
        UniqueConstraint("organization_id", "idempotency_key", name="uq_pilot_sends_idempotency"),
        _org_fk(["authorization_id"], "pilot_authorizations", "fk_pilot_sends_org_authorization"),
        _org_fk(["provider_connection_id"], "provider_connections", "fk_pilot_sends_org_connection"),
        _org_fk(["contact_id"], "contacts", "fk_pilot_sends_org_contact"),
        _org_fk(["draft_id"], "drafts", "fk_pilot_sends_org_draft"),
        _org_fk(["approval_id"], "draft_reviews", "fk_pilot_sends_org_approval"),
        _org_fk(["template_row_id"], "provider_templates", "fk_pilot_sends_org_template"),
        CheckConstraint(f"state IN ({_in(PILOT_STATES)})", name="state"),
        CheckConstraint("preview_digest ~ '^[0-9a-f]{64}$'", name="preview_digest_format"),
        CheckConstraint("nonce_digest ~ '^[0-9a-f]{64}$'", name="nonce_digest_format"),
        CheckConstraint(
            "state IN ('awaiting_confirmation', 'denied', 'expired', 'cancelled') OR confirmed_by IS NOT NULL",
            name="sent_only_after_confirmation",
        ),
        CheckConstraint(
            "(provider_message_id IS NULL) OR state = 'provider_accepted'", name="wamid_only_when_accepted"
        ),
        Index(
            "uq_pilot_sends_in_flight",
            "provider_connection_id",
            unique=True,
            postgresql_where=text("state = 'reserved'"),
        ),  # fmt: skip
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"))
    authorization_id: Mapped[uuid.UUID]
    provider_connection_id: Mapped[uuid.UUID]
    contact_id: Mapped[uuid.UUID]
    draft_id: Mapped[uuid.UUID]
    draft_revision: Mapped[int] = mapped_column(Integer)
    approval_id: Mapped[uuid.UUID]
    template_row_id: Mapped[uuid.UUID]
    template_name: Mapped[str] = mapped_column(String(512))
    template_language: Mapped[str] = mapped_column(String(16))
    template_category: Mapped[str] = mapped_column(String(32))
    components_digest: Mapped[str] = mapped_column(String(64))
    params_json: Mapped[list[str]] = mapped_column(JSONB)
    purpose: Mapped[str] = mapped_column(String(16))
    preview_digest: Mapped[str] = mapped_column(String(64))
    nonce_digest: Mapped[str] = mapped_column(String(64))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    state: Mapped[str] = mapped_column(String(24))
    denial_reason: Mapped[str | None] = mapped_column(String(80))
    provider_message_id: Mapped[str | None] = mapped_column(String(256))
    provider_message_status: Mapped[str | None] = mapped_column(String(40))
    error_class: Mapped[str | None] = mapped_column(String(40))
    provider_error_code: Mapped[str | None] = mapped_column(String(16))
    requested_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    confirmed_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    idempotency_key: Mapped[str] = mapped_column(String(100))
    request_digest: Mapped[str] = mapped_column(String(64))
    simulated_transport: Mapped[bool] = mapped_column(Boolean)  # True only when tests injected a fake
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    version: Mapped[int] = mapped_column(Integer)
