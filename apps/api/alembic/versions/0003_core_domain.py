"""Core domain: verticals, areas, accounts, source_records, account_aliases, account_facts (P1.2).

Reuses P1.1 `organizations`; organization-owned children use composite
(organization_id, id) foreign keys so cross-organization links fail in the database.
Seeds the `schools` vertical (reference data, no customer data).

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-23
"""

import uuid
from collections.abc import Sequence
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHOOLS_VERTICAL_ID = uuid.UUID("5c4f1d2e-0000-4000-8000-000000000001")

ACCOUNT_STATUSES = "'discovered', 'researching', 'assessed', 'shortlisted', 'investigate', 'nurture', 'excluded'"


def _ts(name: str, nullable: bool = False) -> sa.Column[datetime]:
    return sa.Column(name, sa.DateTime(timezone=True), nullable=nullable)


def upgrade() -> None:
    verticals = op.create_table(
        "verticals",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("slug", sa.String(80), nullable=False),
        sa.Column("name", sa.String(160), nullable=False),
        sa.Column("qualifier_config_version", sa.String(80), server_default="unconfigured", nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.CheckConstraint("status IN ('active', 'inactive')", name=op.f("ck_verticals_status")),
        sa.CheckConstraint("slug ~ '^[a-z][a-z0-9_]{1,79}$'", name=op.f("ck_verticals_slug_format")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_verticals")),
        sa.UniqueConstraint("slug", name=op.f("uq_verticals_slug")),
    )
    op.bulk_insert(verticals, [{"id": SCHOOLS_VERTICAL_ID, "slug": "schools", "name": "Schools", "status": "active"}])

    op.create_table(
        "areas",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("city", sa.String(120), nullable=False),
        sa.Column("district_name", sa.String(160), nullable=True),
        sa.Column("source_query", sa.String(400), nullable=True),
        sa.Column("timezone", sa.String(64), server_default="Asia/Karachi", nullable=False),
        _ts("created_at"),
        sa.ForeignKeyConstraint(
            ["organization_id"], ["organizations.id"], name=op.f("fk_areas_organization_id_organizations")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_areas")),
        sa.UniqueConstraint("organization_id", "id", name=op.f("uq_areas_organization_id_id")),
    )
    op.create_index(
        "uq_areas_org_city_district",
        "areas",
        ["organization_id", sa.text("lower(city)"), sa.text("coalesce(lower(district_name), '')")],
        unique=True,
    )

    op.create_table(
        "accounts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("vertical_id", sa.Uuid(), nullable=False),
        sa.Column("canonical_name", sa.String(250), nullable=False),
        sa.Column("normalized_name", sa.String(250), nullable=False),
        sa.Column("city", sa.String(120), nullable=False),
        sa.Column("locality", sa.String(160), nullable=True),
        sa.Column("status", sa.String(16), nullable=False),
        _ts("discovered_at"),
        _ts("updated_at"),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.CheckConstraint(f"status IN ({ACCOUNT_STATUSES})", name=op.f("ck_accounts_status")),
        sa.CheckConstraint("version >= 1", name=op.f("ck_accounts_version_positive")),
        sa.ForeignKeyConstraint(
            ["organization_id"], ["organizations.id"], name=op.f("fk_accounts_organization_id_organizations")
        ),
        sa.ForeignKeyConstraint(["vertical_id"], ["verticals.id"], name=op.f("fk_accounts_vertical_id_verticals")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_accounts")),
        sa.UniqueConstraint("organization_id", "id", name=op.f("uq_accounts_organization_id_id")),
    )
    op.create_index(
        "ix_accounts_org_vertical_city_status", "accounts", ["organization_id", "vertical_id", "city", "status"]
    )
    op.create_index("ix_accounts_org_normalized_name", "accounts", ["organization_id", "normalized_name"])

    op.create_table(
        "source_records",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("provider", sa.String(100), nullable=False),
        sa.Column("external_key", sa.String(300), nullable=True),
        sa.Column("source_url", sa.Text(), nullable=False),
        _ts("observed_at"),
        sa.Column("permitted_storage_class", sa.String(16), nullable=False),
        sa.Column("source_payload_reference", sa.Text(), nullable=True),
        sa.Column("rights_policy_version", sa.String(80), nullable=False),
        _ts("expires_at", nullable=True),
        _ts("created_at"),
        sa.CheckConstraint(
            "permitted_storage_class IN ('metadata_only', 'derived_only', 'full_allowed')",
            name=op.f("ck_source_records_storage_class"),
        ),
        sa.CheckConstraint(
            "source_payload_reference IS NULL OR permitted_storage_class = 'full_allowed'",
            name=op.f("ck_source_records_payload_requires_full_rights"),
        ),
        sa.CheckConstraint(
            "expires_at IS NULL OR expires_at > observed_at", name=op.f("ck_source_records_expires_after_observed")
        ),
        sa.CheckConstraint(
            "length(source_url) <= 2048 AND source_url !~ '\\s'", name=op.f("ck_source_records_source_url_shape")
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"], ["organizations.id"], name=op.f("fk_source_records_organization_id_organizations")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_source_records")),
        sa.UniqueConstraint("organization_id", "id", name=op.f("uq_source_records_organization_id_id")),
    )
    op.create_index(
        "uq_source_records_org_provider_external_key",
        "source_records",
        ["organization_id", "provider", "external_key"],
        unique=True,
        postgresql_where=sa.text("external_key IS NOT NULL"),
    )

    op.create_table(
        "account_aliases",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("account_id", sa.Uuid(), nullable=False),
        sa.Column("normalized_name", sa.String(250), nullable=False),
        sa.Column("source_record_id", sa.Uuid(), nullable=True),
        _ts("created_at"),
        sa.ForeignKeyConstraint(
            ["organization_id", "account_id"],
            ["accounts.organization_id", "accounts.id"],
            name="fk_account_aliases_org_account",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "source_record_id"],
            ["source_records.organization_id", "source_records.id"],
            name="fk_account_aliases_org_source",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"], ["organizations.id"], name=op.f("fk_account_aliases_organization_id_organizations")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_account_aliases")),
        sa.UniqueConstraint(
            "organization_id",
            "account_id",
            "normalized_name",
            name=op.f("uq_account_aliases_organization_id_account_id_normalized_name"),
        ),
    )

    op.create_table(
        "account_facts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("account_id", sa.Uuid(), nullable=False),
        sa.Column("claim_type", sa.String(100), nullable=False),
        sa.Column("typed_value_json", postgresql.JSONB(), nullable=False),
        sa.Column("confidence_label", sa.String(16), nullable=False),
        sa.Column("verification_status", sa.String(24), nullable=False),
        sa.Column("source_record_id", sa.Uuid(), nullable=True),
        sa.Column("evidence_excerpt", sa.Text(), nullable=True),
        _ts("observed_at"),
        _ts("expires_at", nullable=True),
        _ts("created_at"),
        sa.CheckConstraint(
            "confidence_label IN ('strong', 'moderate', 'weak', 'unknown')",
            name=op.f("ck_account_facts_confidence_label"),
        ),
        sa.CheckConstraint(
            "verification_status IN ('source_supported', 'hypothesis', 'disputed', 'rejected')",
            name=op.f("ck_account_facts_verification_status"),
        ),
        sa.CheckConstraint(
            "verification_status <> 'source_supported' OR source_record_id IS NOT NULL",
            name=op.f("ck_account_facts_supported_requires_source"),
        ),
        sa.CheckConstraint(
            "verification_status <> 'source_supported' OR confidence_label <> 'unknown'",
            name=op.f("ck_account_facts_supported_not_unknown"),
        ),
        sa.CheckConstraint("claim_type ~ '^[a-z][a-z0-9_]{1,99}$'", name=op.f("ck_account_facts_claim_type_format")),
        sa.CheckConstraint(
            "evidence_excerpt IS NULL OR char_length(evidence_excerpt) <= 1000",
            name=op.f("ck_account_facts_excerpt_length"),
        ),
        sa.CheckConstraint(
            "expires_at IS NULL OR expires_at > observed_at", name=op.f("ck_account_facts_expires_after_observed")
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "account_id"],
            ["accounts.organization_id", "accounts.id"],
            name="fk_account_facts_org_account",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "source_record_id"],
            ["source_records.organization_id", "source_records.id"],
            name="fk_account_facts_org_source",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"], ["organizations.id"], name=op.f("fk_account_facts_organization_id_organizations")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_account_facts")),
    )
    op.create_index(
        "ix_account_facts_org_account_claim_observed",
        "account_facts",
        ["organization_id", "account_id", "claim_type", "observed_at"],
    )


def downgrade() -> None:
    # Reverse order; P1.1 identity tables are untouched. Data-bearing environments:
    # back up first and prefer a reviewed forward repair (docs/contracts/core-domain.md).
    op.drop_index("ix_account_facts_org_account_claim_observed", table_name="account_facts")
    op.drop_table("account_facts")
    op.drop_table("account_aliases")
    op.drop_index("uq_source_records_org_provider_external_key", table_name="source_records")
    op.drop_table("source_records")
    op.drop_index("ix_accounts_org_normalized_name", table_name="accounts")
    op.drop_index("ix_accounts_org_vertical_city_status", table_name="accounts")
    op.drop_table("accounts")
    op.drop_index("uq_areas_org_city_district", table_name="areas")
    op.drop_table("areas")
    op.drop_table("verticals")
