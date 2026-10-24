"""Discovery staging: source_imports and discovery_candidates (P2.2).

Revision ID: 0007
Revises: 0006
Create Date: 2026-10-24
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "source_imports",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("provider", sa.String(100), nullable=False),
        sa.Column("file_sha256", sa.String(64), nullable=False),
        sa.Column("source_label", sa.String(200), nullable=False),
        sa.Column("permission_declaration", sa.Text(), nullable=False),
        sa.Column("row_count", sa.Integer(), nullable=False),
        sa.Column("accepted_count", sa.Integer(), nullable=False),
        sa.Column("rejected_count", sa.Integer(), nullable=False),
        sa.Column("imported_by", sa.Uuid(), nullable=False),
        sa.Column("imported_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("file_sha256 ~ '^[0-9a-f]{64}$'", name=op.f("ck_source_imports_file_sha256_format")),
        sa.CheckConstraint(
            "char_length(permission_declaration) BETWEEN 20 AND 1000", name=op.f("ck_source_imports_declaration_length")
        ),
        sa.CheckConstraint(
            "row_count >= 0 AND accepted_count >= 0 AND rejected_count >= 0", name=op.f("ck_source_imports_counts")
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "imported_by"], ["users.organization_id", "users.id"], name="fk_source_imports_org_user"
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"], ["organizations.id"], name=op.f("fk_source_imports_organization_id_organizations")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_source_imports")),
        sa.UniqueConstraint(
            "organization_id",
            "provider",
            "file_sha256",
            name=op.f("uq_source_imports_organization_id_provider_file_sha256"),
        ),
        sa.UniqueConstraint("organization_id", "id", name=op.f("uq_source_imports_organization_id_id")),
    )
    op.create_table(
        "discovery_candidates",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("provider", sa.String(100), nullable=False),
        sa.Column("external_key", sa.String(300), nullable=False),
        sa.Column("source_record_id", sa.Uuid(), nullable=True),
        sa.Column("source_import_id", sa.Uuid(), nullable=True),
        sa.Column("display_name", sa.String(250), nullable=False),
        sa.Column("name_local", sa.String(250), nullable=True),
        sa.Column("city", sa.String(120), nullable=False),
        sa.Column("locality", sa.String(160), nullable=True),
        sa.Column("latitude", sa.Numeric(9, 6), nullable=True),
        sa.Column("longitude", sa.Numeric(9, 6), nullable=True),
        sa.Column("location_precision", sa.String(16), nullable=True),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("upstream_timestamp", sa.DateTime(timezone=True), nullable=True),
        sa.Column("rights_policy_version", sa.String(80), nullable=False),
        sa.Column("attribution", sa.String(300), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("revision", sa.Integer(), server_default="1", nullable=False),
        sa.Column("payload_digest", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('unreviewed', 'admitted', 'rejected')", name=op.f("ck_discovery_candidates_status")
        ),
        sa.CheckConstraint(
            "location_precision IS NULL OR location_precision IN ('point', 'area_center')",
            name=op.f("ck_discovery_candidates_location_precision"),
        ),
        sa.CheckConstraint(
            "(latitude IS NULL) = (longitude IS NULL)", name=op.f("ck_discovery_candidates_coordinates_pair")
        ),
        sa.CheckConstraint(
            "latitude IS NULL OR latitude BETWEEN -90 AND 90", name=op.f("ck_discovery_candidates_latitude_range")
        ),
        sa.CheckConstraint(
            "longitude IS NULL OR longitude BETWEEN -180 AND 180", name=op.f("ck_discovery_candidates_longitude_range")
        ),
        sa.CheckConstraint(
            "(source_record_id IS NOT NULL) OR (source_import_id IS NOT NULL)",
            name=op.f("ck_discovery_candidates_has_provenance"),
        ),
        sa.CheckConstraint("revision >= 1", name=op.f("ck_discovery_candidates_revision_positive")),
        sa.CheckConstraint(
            "payload_digest ~ '^[0-9a-f]{64}$'", name=op.f("ck_discovery_candidates_payload_digest_format")
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "source_record_id"],
            ["source_records.organization_id", "source_records.id"],
            name="fk_discovery_candidates_org_source",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "source_import_id"],
            ["source_imports.organization_id", "source_imports.id"],
            name="fk_discovery_candidates_org_import",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("fk_discovery_candidates_organization_id_organizations"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_discovery_candidates")),
        sa.UniqueConstraint(
            "organization_id",
            "provider",
            "external_key",
            name=op.f("uq_discovery_candidates_organization_id_provider_external_key"),
        ),
        sa.UniqueConstraint("organization_id", "id", name=op.f("uq_discovery_candidates_organization_id_id")),
    )


def downgrade() -> None:
    # Candidates and imports are reviewable provenance: on data-bearing databases export first.
    op.drop_table("discovery_candidates")
    op.drop_table("source_imports")
