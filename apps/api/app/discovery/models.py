"""Discovery staging (P2.2): review-ready candidates and operator seed imports.

A candidate is NOT an account (Batch 04 rule 3): staging rows hold only
rights-permitted listing fields and provenance; accounts are created only by
a later, explicit review action (P2.4).
"""

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.persistence.base import Base


class SourceImport(Base):
    """One operator-supplied seed file (e.g. CSV), idempotent per (org, provider, file checksum)."""

    __tablename__ = "source_imports"
    __table_args__ = (
        UniqueConstraint("organization_id", "provider", "file_sha256"),
        UniqueConstraint("organization_id", "id"),
        ForeignKeyConstraint(
            ["organization_id", "imported_by"], ["users.organization_id", "users.id"], name="fk_source_imports_org_user"
        ),
        CheckConstraint("file_sha256 ~ '^[0-9a-f]{64}$'", name="file_sha256_format"),
        CheckConstraint("char_length(permission_declaration) BETWEEN 20 AND 1000", name="declaration_length"),
        CheckConstraint("row_count >= 0 AND accepted_count >= 0 AND rejected_count >= 0", name="counts"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"))
    provider: Mapped[str] = mapped_column(String(100))
    file_sha256: Mapped[str] = mapped_column(String(64))
    source_label: Mapped[str] = mapped_column(String(200))
    permission_declaration: Mapped[str] = mapped_column(Text)
    row_count: Mapped[int] = mapped_column(Integer)
    accepted_count: Mapped[int] = mapped_column(Integer)
    rejected_count: Mapped[int] = mapped_column(Integer)
    imported_by: Mapped[uuid.UUID]
    imported_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class DiscoveryCandidate(Base):
    __tablename__ = "discovery_candidates"
    __table_args__ = (
        UniqueConstraint("organization_id", "provider", "external_key"),
        UniqueConstraint("organization_id", "id"),
        ForeignKeyConstraint(
            ["organization_id", "source_record_id"],
            ["source_records.organization_id", "source_records.id"],
            name="fk_discovery_candidates_org_source",
        ),
        ForeignKeyConstraint(
            ["organization_id", "source_import_id"],
            ["source_imports.organization_id", "source_imports.id"],
            name="fk_discovery_candidates_org_import",
        ),
        CheckConstraint("status IN ('unreviewed', 'admitted', 'rejected')", name="status"),
        CheckConstraint(
            "location_precision IS NULL OR location_precision IN ('point', 'area_center')", name="location_precision"
        ),
        CheckConstraint("(latitude IS NULL) = (longitude IS NULL)", name="coordinates_pair"),
        CheckConstraint("latitude IS NULL OR latitude BETWEEN -90 AND 90", name="latitude_range"),
        CheckConstraint("longitude IS NULL OR longitude BETWEEN -180 AND 180", name="longitude_range"),
        CheckConstraint("(source_record_id IS NOT NULL) OR (source_import_id IS NOT NULL)", name="has_provenance"),
        CheckConstraint("revision >= 1", name="revision_positive"),
        CheckConstraint("payload_digest ~ '^[0-9a-f]{64}$'", name="payload_digest_format"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"))
    provider: Mapped[str] = mapped_column(String(100))
    external_key: Mapped[str] = mapped_column(String(300))
    source_record_id: Mapped[uuid.UUID | None]
    source_import_id: Mapped[uuid.UUID | None]
    display_name: Mapped[str] = mapped_column(String(250))
    name_local: Mapped[str | None] = mapped_column(String(250))
    city: Mapped[str] = mapped_column(String(120))
    locality: Mapped[str | None] = mapped_column(String(160))
    latitude: Mapped[Decimal | None] = mapped_column(Numeric(9, 6))
    longitude: Mapped[Decimal | None] = mapped_column(Numeric(9, 6))
    location_precision: Mapped[str | None] = mapped_column(String(16))
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    upstream_timestamp: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    rights_policy_version: Mapped[str] = mapped_column(String(80))
    attribution: Mapped[str | None] = mapped_column(String(300))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(16))
    revision: Mapped[int] = mapped_column(Integer, server_default="1")
    payload_digest: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


RUN_STATUSES = ("pending", "running", "completed", "partial", "failed", "cancelled")
RUN_TERMINAL = frozenset({"completed", "partial", "failed", "cancelled"})
REVIEW_STATUSES = ("pending", "accepted", "rejected", "deferred")


class DiscoveryRun(Base):
    """One operator-requested, bounded discovery run (P2.4). `completed` never means exhaustive."""

    __tablename__ = "discovery_runs"
    __table_args__ = (
        UniqueConstraint("organization_id", "id"),
        UniqueConstraint("organization_id", "idempotency_key"),
        ForeignKeyConstraint(
            ["organization_id", "created_by"],
            ["users.organization_id", "users.id"],
            name="fk_discovery_runs_org_creator",
        ),
        ForeignKeyConstraint(
            ["organization_id", "job_id"], ["jobs.organization_id", "jobs.id"], name="fk_discovery_runs_org_job"
        ),
        CheckConstraint(
            "status IN ('pending', 'running', 'completed', 'partial', 'failed', 'cancelled')", name="status"
        ),
        CheckConstraint("idempotency_key ~ '^[A-Za-z0-9._:-]{8,100}$'", name="idempotency_key_format"),
        CheckConstraint("request_digest ~ '^[0-9a-f]{64}$'", name="request_digest_format"),
        CheckConstraint(
            "examined_count >= 0 AND staged_count >= 0 AND rejected_count >= 0 AND displayed_count BETWEEN 0 AND 30",
            name="counts",
        ),
        CheckConstraint(
            "status NOT IN ('completed', 'partial', 'failed', 'cancelled') OR finished_at IS NOT NULL",
            name="terminal_has_finish",
        ),
        CheckConstraint("version >= 1", name="version_positive"),
        Index("ix_discovery_runs_org_created", "organization_id", "created_at", "id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"))
    created_by: Mapped[uuid.UUID]
    vertical_slug: Mapped[str] = mapped_column(String(80))
    city: Mapped[str] = mapped_column(String(120))
    area_label: Mapped[str] = mapped_column(String(300))
    provider: Mapped[str] = mapped_column(String(100))
    adapter_version: Mapped[str] = mapped_column(String(40))
    rights_policy_version: Mapped[str] = mapped_column(String(80))
    attribution: Mapped[str | None] = mapped_column(String(300))
    budget_json: Mapped[dict[str, Any]] = mapped_column(JSONB)
    usage_json: Mapped[dict[str, Any]] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(String(16))
    examined_count: Mapped[int] = mapped_column(Integer)
    staged_count: Mapped[int] = mapped_column(Integer)
    rejected_count: Mapped[int] = mapped_column(Integer)
    displayed_count: Mapped[int] = mapped_column(Integer)
    truncated: Mapped[bool] = mapped_column(Boolean)
    stop_reason: Mapped[str | None] = mapped_column(String(40))
    partial_reason: Mapped[str | None] = mapped_column(String(80))
    error_code: Mapped[str | None] = mapped_column(String(80))
    idempotency_key: Mapped[str] = mapped_column(String(100))
    request_digest: Mapped[str] = mapped_column(String(64))
    job_id: Mapped[uuid.UUID | None]
    requested_cancel_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    version: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class DiscoveryRunCandidate(Base):
    """A staged candidate shown in a run (many-to-many: a candidate can recur across runs)."""

    __tablename__ = "discovery_run_candidates"
    __table_args__ = (
        UniqueConstraint("organization_id", "run_id", "candidate_id"),
        UniqueConstraint("organization_id", "id"),
        ForeignKeyConstraint(
            ["organization_id", "run_id"], ["discovery_runs.organization_id", "discovery_runs.id"],
            name="fk_drc_org_run",
        ),
        ForeignKeyConstraint(
            ["organization_id", "candidate_id"],
            ["discovery_candidates.organization_id", "discovery_candidates.id"],
            name="fk_drc_org_candidate",
        ),
        ForeignKeyConstraint(
            ["organization_id", "account_id"], ["accounts.organization_id", "accounts.id"], name="fk_drc_org_account"
        ),
        ForeignKeyConstraint(
            ["organization_id", "reviewed_by"], ["users.organization_id", "users.id"], name="fk_drc_org_reviewer"
        ),
        CheckConstraint("display_status IN ('pending', 'accepted', 'rejected', 'deferred')", name="display_status"),
        CheckConstraint("display_status <> 'accepted' OR account_id IS NOT NULL", name="accepted_has_account"),
        CheckConstraint("version >= 1", name="version_positive"),
    )  # fmt: skip

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"))
    run_id: Mapped[uuid.UUID]
    candidate_id: Mapped[uuid.UUID]
    position: Mapped[int] = mapped_column(Integer)
    display_status: Mapped[str] = mapped_column(String(16))
    account_id: Mapped[uuid.UUID | None]
    review_note: Mapped[str | None] = mapped_column(Text)
    reviewed_by: Mapped[uuid.UUID | None]
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    version: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class DiscoveryReviewDecision(Base):
    """Append-only (database trigger): every reviewer command on a run candidate and its effect."""

    __tablename__ = "discovery_review_decisions"
    __table_args__ = (
        UniqueConstraint("organization_id", "idempotency_key"),
        ForeignKeyConstraint(
            ["organization_id", "run_id"], ["discovery_runs.organization_id", "discovery_runs.id"],
            name="fk_drd_org_run",
        ),
        ForeignKeyConstraint(
            ["organization_id", "candidate_id"],
            ["discovery_candidates.organization_id", "discovery_candidates.id"],
            name="fk_drd_org_candidate",
        ),
        ForeignKeyConstraint(
            ["organization_id", "account_id"], ["accounts.organization_id", "accounts.id"], name="fk_drd_org_account"
        ),
        ForeignKeyConstraint(
            ["organization_id", "actor_user_id"], ["users.organization_id", "users.id"], name="fk_drd_org_actor"
        ),
        CheckConstraint("action IN ('accept_new', 'attach_existing', 'reject', 'defer')", name="action"),
        CheckConstraint("idempotency_key ~ '^[A-Za-z0-9._:-]{8,100}$'", name="idempotency_key_format"),
        CheckConstraint("payload_digest ~ '^[0-9a-f]{64}$'", name="payload_digest_format"),
        CheckConstraint("char_length(reason) BETWEEN 3 AND 1000", name="reason_length"),
        Index("ix_drd_org_run_candidate", "organization_id", "run_id", "candidate_id", "recorded_at"),
    )  # fmt: skip

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"))
    run_id: Mapped[uuid.UUID]
    candidate_id: Mapped[uuid.UUID]
    idempotency_key: Mapped[str] = mapped_column(String(100))
    action: Mapped[str] = mapped_column(String(24))
    payload_digest: Mapped[str] = mapped_column(String(64))
    prior_status: Mapped[str] = mapped_column(String(16))
    next_status: Mapped[str] = mapped_column(String(16))
    account_id: Mapped[uuid.UUID | None]
    converged: Mapped[bool] = mapped_column(Boolean)
    actor_user_id: Mapped[uuid.UUID]
    reason: Mapped[str] = mapped_column(Text)
    request_id: Mapped[str | None] = mapped_column(String(64))
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
