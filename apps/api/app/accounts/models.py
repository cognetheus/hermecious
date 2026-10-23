"""Core sales data (P1.2): verticals, areas, accounts, sources, aliases and facts.

Every organization-owned child references its parent through a composite
`(organization_id, id)` foreign key, so the database itself rejects links
across organizations. Schema contract: docs/contracts/core-domain.md.
"""

import uuid
from datetime import datetime
from enum import StrEnum
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
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.persistence.base import Base


class AccountStatus(StrEnum):
    DISCOVERED = "discovered"
    RESEARCHING = "researching"
    ASSESSED = "assessed"
    SHORTLISTED = "shortlisted"
    INVESTIGATE = "investigate"
    NURTURE = "nurture"
    EXCLUDED = "excluded"


class StorageClass(StrEnum):
    METADATA_ONLY = "metadata_only"
    DERIVED_ONLY = "derived_only"
    FULL_ALLOWED = "full_allowed"


class ConfidenceLabel(StrEnum):
    STRONG = "strong"
    MODERATE = "moderate"
    WEAK = "weak"
    UNKNOWN = "unknown"


class VerificationStatus(StrEnum):
    SOURCE_SUPPORTED = "source_supported"
    HYPOTHESIS = "hypothesis"
    DISPUTED = "disputed"
    REJECTED = "rejected"


def _in(values: type[StrEnum]) -> str:
    return ", ".join(f"'{v.value}'" for v in values)


class Vertical(Base):
    __tablename__ = "verticals"
    __table_args__ = (
        CheckConstraint("status IN ('active', 'inactive')", name="status"),
        CheckConstraint("slug ~ '^[a-z][a-z0-9_]{1,79}$'", name="slug_format"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    slug: Mapped[str] = mapped_column(String(80), unique=True)
    name: Mapped[str] = mapped_column(String(160))
    qualifier_config_version: Mapped[str] = mapped_column(String(80), server_default="unconfigured")
    status: Mapped[str] = mapped_column(String(16))


class Area(Base):
    __tablename__ = "areas"
    __table_args__ = (
        UniqueConstraint("organization_id", "id"),
        # Nullable district: one area per (org, city, district or "whole city"), case-insensitively.
        Index(
            "uq_areas_org_city_district",
            "organization_id",
            func.lower(text("city")),
            func.coalesce(func.lower(text("district_name")), ""),
            unique=True,
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"))
    city: Mapped[str] = mapped_column(String(120))
    district_name: Mapped[str | None] = mapped_column(String(160))
    source_query: Mapped[str | None] = mapped_column(String(400))
    timezone: Mapped[str] = mapped_column(String(64), server_default="Asia/Karachi")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Account(Base):
    __tablename__ = "accounts"
    __table_args__ = (
        UniqueConstraint("organization_id", "id"),
        CheckConstraint(f"status IN ({_in(AccountStatus)})", name="status"),
        CheckConstraint("version >= 1", name="version_positive"),
        Index("ix_accounts_org_vertical_city_status", "organization_id", "vertical_id", "city", "status"),
        Index("ix_accounts_org_normalized_name", "organization_id", "normalized_name"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"))
    vertical_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("verticals.id"))
    canonical_name: Mapped[str] = mapped_column(String(250))
    normalized_name: Mapped[str] = mapped_column(String(250))
    city: Mapped[str] = mapped_column(String(120))
    locality: Mapped[str | None] = mapped_column(String(160))
    status: Mapped[str] = mapped_column(String(16))
    discovered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    version: Mapped[int] = mapped_column(Integer, server_default="1")

    # Optimistic concurrency: UPDATEs include `WHERE version = :expected` and bump it.
    __mapper_args__ = {"version_id_col": version}  # noqa: RUF012


class SourceRecord(Base):
    __tablename__ = "source_records"
    __table_args__ = (
        UniqueConstraint("organization_id", "id"),
        CheckConstraint(f"permitted_storage_class IN ({_in(StorageClass)})", name="storage_class"),
        CheckConstraint(
            "source_payload_reference IS NULL OR permitted_storage_class = 'full_allowed'",
            name="payload_requires_full_rights",
        ),
        CheckConstraint("expires_at IS NULL OR expires_at > observed_at", name="expires_after_observed"),
        CheckConstraint("length(source_url) <= 2048 AND source_url !~ '\\s'", name="source_url_shape"),
        Index(
            "uq_source_records_org_provider_external_key",
            "organization_id",
            "provider",
            "external_key",
            unique=True,
            postgresql_where=text("external_key IS NOT NULL"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"))
    provider: Mapped[str] = mapped_column(String(100))
    external_key: Mapped[str | None] = mapped_column(String(300))
    source_url: Mapped[str] = mapped_column(Text)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    permitted_storage_class: Mapped[str] = mapped_column(String(16))
    source_payload_reference: Mapped[str | None] = mapped_column(Text)
    rights_policy_version: Mapped[str] = mapped_column(String(80))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class AccountAlias(Base):
    __tablename__ = "account_aliases"
    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id", "account_id"],
            ["accounts.organization_id", "accounts.id"],
            name="fk_account_aliases_org_account",
        ),
        ForeignKeyConstraint(
            ["organization_id", "source_record_id"],
            ["source_records.organization_id", "source_records.id"],
            name="fk_account_aliases_org_source",
        ),
        UniqueConstraint("organization_id", "account_id", "normalized_name"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"))
    account_id: Mapped[uuid.UUID]
    normalized_name: Mapped[str] = mapped_column(String(250))
    source_record_id: Mapped[uuid.UUID | None]
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class AccountFact(Base):
    __tablename__ = "account_facts"
    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id", "account_id"],
            ["accounts.organization_id", "accounts.id"],
            name="fk_account_facts_org_account",
        ),
        ForeignKeyConstraint(
            ["organization_id", "source_record_id"],
            ["source_records.organization_id", "source_records.id"],
            name="fk_account_facts_org_source",
        ),
        CheckConstraint(f"confidence_label IN ({_in(ConfidenceLabel)})", name="confidence_label"),
        CheckConstraint(f"verification_status IN ({_in(VerificationStatus)})", name="verification_status"),
        CheckConstraint(
            "verification_status <> 'source_supported' OR source_record_id IS NOT NULL",
            name="supported_requires_source",
        ),
        CheckConstraint(
            "verification_status <> 'source_supported' OR confidence_label <> 'unknown'",
            name="supported_not_unknown",
        ),
        CheckConstraint("claim_type ~ '^[a-z][a-z0-9_]{1,99}$'", name="claim_type_format"),
        CheckConstraint("evidence_excerpt IS NULL OR char_length(evidence_excerpt) <= 1000", name="excerpt_length"),
        CheckConstraint("expires_at IS NULL OR expires_at > observed_at", name="expires_after_observed"),
        Index(
            "ix_account_facts_org_account_claim_observed", "organization_id", "account_id", "claim_type", "observed_at"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"))
    account_id: Mapped[uuid.UUID]
    claim_type: Mapped[str] = mapped_column(String(100))
    typed_value_json: Mapped[dict[str, Any]] = mapped_column(JSONB)
    confidence_label: Mapped[str] = mapped_column(String(16))
    verification_status: Mapped[str] = mapped_column(String(24))
    source_record_id: Mapped[uuid.UUID | None]
    evidence_excerpt: Mapped[str | None] = mapped_column(Text)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
