"""Source-backed account research (P3.1, ADR-016).

`research_runs`: one bounded run over ≤5 sources associated with an account.
`research_observations`: per-source outcome; a content hash and counts only, never the page body.
`research_claims`: proposed typed claims with an exact locator. The excerpt text is stored only for
`full_allowed` sources. A claim becomes a P1.4 fact only through reviewer acceptance.
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
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.persistence.base import Base

RESEARCH_TERMINAL = frozenset({"completed", "partial", "failed", "cancelled"})


class ResearchRun(Base):
    __tablename__ = "research_runs"
    __table_args__ = (
        UniqueConstraint("organization_id", "id"),
        UniqueConstraint("organization_id", "idempotency_key"),
        ForeignKeyConstraint(
            ["organization_id", "account_id"], ["accounts.organization_id", "accounts.id"],
            name="fk_research_runs_org_account",
        ),
        ForeignKeyConstraint(
            ["organization_id", "requested_by"], ["users.organization_id", "users.id"],
            name="fk_research_runs_org_requester",
        ),
        ForeignKeyConstraint(
            ["organization_id", "job_id"], ["jobs.organization_id", "jobs.id"], name="fk_research_runs_org_job"
        ),
        CheckConstraint(
            "status IN ('pending', 'running', 'completed', 'partial', 'failed', 'cancelled')", name="status"
        ),
        CheckConstraint("idempotency_key ~ '^[A-Za-z0-9._:-]{8,100}$'", name="idempotency_key_format"),
        CheckConstraint("request_digest ~ '^[0-9a-f]{64}$'", name="request_digest_format"),
        CheckConstraint("jsonb_array_length(source_record_ids) BETWEEN 1 AND 5", name="source_count"),
        CheckConstraint("claims_proposed BETWEEN 0 AND 25", name="claims_bound"),
        CheckConstraint(
            "status NOT IN ('completed', 'partial', 'failed', 'cancelled') OR finished_at IS NOT NULL",
            name="terminal_has_finish",
        ),
        CheckConstraint("version >= 1", name="version_positive"),
        Index("ix_research_runs_org_account_created", "organization_id", "account_id", "created_at"),
    )  # fmt: skip

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"))
    account_id: Mapped[uuid.UUID]
    requested_by: Mapped[uuid.UUID]
    source_record_ids: Mapped[list[str]] = mapped_column(JSONB)
    extractor_version: Mapped[str] = mapped_column(String(40))
    budget_json: Mapped[dict[str, Any]] = mapped_column(JSONB)
    usage_json: Mapped[dict[str, Any]] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(String(16))
    sources_processed: Mapped[int] = mapped_column(Integer)
    sources_failed: Mapped[int] = mapped_column(Integer)
    claims_proposed: Mapped[int] = mapped_column(Integer)
    claims_abstained: Mapped[int] = mapped_column(Integer)
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


class ResearchObservation(Base):
    """What happened to one source in one run. Holds no page text."""

    __tablename__ = "research_observations"
    __table_args__ = (
        UniqueConstraint("organization_id", "id"),
        UniqueConstraint("organization_id", "run_id", "source_record_id", name="uq_research_obs_run_source"),
        ForeignKeyConstraint(
            ["organization_id", "run_id"], ["research_runs.organization_id", "research_runs.id"],
            name="fk_research_obs_org_run",
        ),
        ForeignKeyConstraint(
            ["organization_id", "source_record_id"], ["source_records.organization_id", "source_records.id"],
            name="fk_research_obs_org_source",
        ),
        CheckConstraint("status IN ('processed', 'skipped', 'failed')", name="status"),
        CheckConstraint("content_sha256 IS NULL OR content_sha256 ~ '^[0-9a-f]{64}$'", name="content_sha256_format"),
        CheckConstraint("normalized_chars BETWEEN 0 AND 60000", name="normalized_chars_bound"),
    )  # fmt: skip

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"))
    run_id: Mapped[uuid.UUID]
    source_record_id: Mapped[uuid.UUID]
    status: Mapped[str] = mapped_column(String(16))
    reason_code: Mapped[str | None] = mapped_column(String(80))
    storage_class: Mapped[str] = mapped_column(String(16))
    rights_policy_version: Mapped[str] = mapped_column(String(80))
    content_sha256: Mapped[str | None] = mapped_column(String(64))
    normalized_chars: Mapped[int] = mapped_column(Integer)
    truncated: Mapped[bool] = mapped_column(Boolean)
    language: Mapped[str | None] = mapped_column(String(8))
    retrieved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ResearchClaim(Base):
    __tablename__ = "research_claims"
    __table_args__ = (
        UniqueConstraint("organization_id", "id"),
        UniqueConstraint(
            "organization_id", "observation_id", "claim_type", "locator_start", "locator_end",
            name="uq_research_claims_span",
        ),
        UniqueConstraint("organization_id", "review_key"),
        ForeignKeyConstraint(
            ["organization_id", "run_id"], ["research_runs.organization_id", "research_runs.id"],
            name="fk_research_claims_org_run",
        ),
        ForeignKeyConstraint(
            ["organization_id", "account_id"], ["accounts.organization_id", "accounts.id"],
            name="fk_research_claims_org_account",
        ),
        ForeignKeyConstraint(
            ["organization_id", "observation_id"],
            ["research_observations.organization_id", "research_observations.id"],
            name="fk_research_claims_org_obs",
        ),
        ForeignKeyConstraint(
            ["organization_id", "source_record_id"], ["source_records.organization_id", "source_records.id"],
            name="fk_research_claims_org_source",
        ),
        ForeignKeyConstraint(
            ["organization_id", "fact_id"], ["account_facts.organization_id", "account_facts.id"],
            name="fk_research_claims_org_fact",
        ),
        ForeignKeyConstraint(
            ["organization_id", "reviewed_by"], ["users.organization_id", "users.id"],
            name="fk_research_claims_org_reviewer",
        ),
        CheckConstraint("status IN ('proposed', 'accepted', 'rejected')", name="status"),
        CheckConstraint("locator_start >= 0 AND locator_end > locator_start AND locator_end - locator_start <= 1000",
                        name="locator_bounds"),
        CheckConstraint("excerpt IS NULL OR char_length(excerpt) <= 1000", name="excerpt_length"),
        CheckConstraint("excerpt IS NULL OR storage_class = 'full_allowed'", name="excerpt_requires_full_rights"),
        CheckConstraint("span_sha256 ~ '^[0-9a-f]{64}$'", name="span_sha256_format"),
        CheckConstraint("status <> 'accepted' OR fact_id IS NOT NULL", name="accepted_has_fact"),
        CheckConstraint("version >= 1", name="version_positive"),
        Index("ix_research_claims_org_account_status", "organization_id", "account_id", "status"),
    )  # fmt: skip

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"))
    run_id: Mapped[uuid.UUID]
    account_id: Mapped[uuid.UUID]
    observation_id: Mapped[uuid.UUID]
    source_record_id: Mapped[uuid.UUID]
    claim_type: Mapped[str] = mapped_column(String(100))
    typed_value_json: Mapped[dict[str, Any]] = mapped_column(JSONB)
    rule_id: Mapped[str] = mapped_column(String(60))
    extractor_version: Mapped[str] = mapped_column(String(40))
    storage_class: Mapped[str] = mapped_column(String(16))
    language: Mapped[str] = mapped_column(String(8))
    locator_start: Mapped[int] = mapped_column(Integer)
    locator_end: Mapped[int] = mapped_column(Integer)
    span_sha256: Mapped[str] = mapped_column(String(64))
    excerpt: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16))
    fact_id: Mapped[uuid.UUID | None]
    review_key: Mapped[str | None] = mapped_column(String(100))
    review_reason: Mapped[str | None] = mapped_column(Text)
    reviewed_by: Mapped[uuid.UUID | None]
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    version: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
