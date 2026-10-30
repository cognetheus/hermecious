"""WhatsApp Cloud API provider connections (P5.1).

Revision ID: 0020
Revises: 0019
Create Date: 2026-10-29
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0020"
down_revision: str | None = "0019"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "provider_connections",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("waba_id", sa.String(20), nullable=False),
        sa.Column("phone_number_id", sa.String(20), nullable=False),
        sa.Column("graph_version", sa.String(8), nullable=False),
        sa.Column("mode", sa.String(16), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("credential_ref", sa.String(80), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.CheckConstraint("provider = 'meta_whatsapp'", name=op.f("ck_provider_connections_provider")),
        sa.CheckConstraint(
            "mode IN ('contract_test', 'provider_test', 'production')", name=op.f("ck_provider_connections_mode")
        ),
        sa.CheckConstraint(
            "waba_id ~ '^[0-9]{5,20}$' AND phone_number_id ~ '^[0-9]{5,20}$'",
            name=op.f("ck_provider_connections_meta_ids"),
        ),
        sa.CheckConstraint("graph_version ~ '^v[0-9]{2}\\.0$'", name=op.f("ck_provider_connections_graph_version")),
        sa.CheckConstraint("credential_ref LIKE 'env:%'", name=op.f("ck_provider_connections_credential_ref")),
        sa.CheckConstraint("version >= 1", name=op.f("ck_provider_connections_version_positive")),
        sa.ForeignKeyConstraint(
            ["organization_id", "created_by"],
            ["users.organization_id", "users.id"],
            name="fk_provider_connections_org_creator",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("fk_provider_connections_organization_id_organizations"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_provider_connections")),
        sa.UniqueConstraint("organization_id", "id", name=op.f("uq_provider_connections_organization_id_id")),
        sa.UniqueConstraint("provider", "phone_number_id", name="uq_provider_connections_phone"),
        sa.UniqueConstraint("organization_id", "provider", name="uq_provider_connections_org"),
    )


def downgrade() -> None:
    op.drop_table("provider_connections")
