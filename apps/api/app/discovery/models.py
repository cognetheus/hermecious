"""Discovery staging (P2.2): review-ready candidates and operator seed imports.

A candidate is NOT an account (Batch 04 rule 3): staging rows hold only
rights-permitted listing fields and provenance; accounts are created only by
a later, explicit review action (P2.4).
"""

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
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
