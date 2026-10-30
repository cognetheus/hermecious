"""WhatsApp template catalog, test-recipient registry and guarded test sends (P5.3).

Revision ID: 0022
Revises: 0021
Create Date: 2026-10-30
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0022"
down_revision: str | None = "0021"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

STATES = (
    "'awaiting_confirmation', 'reserved', 'provider_accepted', 'definitively_rejected', 'indeterminate', 'denied',"
    " 'expired', 'cancelled'"
)


def _fk(cols: list[str], target: str, name: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(["organization_id", *cols], [f"{target}.organization_id", f"{target}.id"], name=name)


def _base(table: str) -> list[sa.Constraint]:
    return [
        sa.PrimaryKeyConstraint("id", name=op.f(f"pk_{table}")),
        sa.UniqueConstraint("organization_id", "id", name=op.f(f"uq_{table}_organization_id_id")),
        sa.ForeignKeyConstraint(
            ["organization_id"], ["organizations.id"], name=op.f(f"fk_{table}_organization_id_organizations")
        ),
    ]


def upgrade() -> None:
    op.create_table(
        "provider_templates",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("provider_connection_id", sa.Uuid(), nullable=False),
        sa.Column("template_id", sa.String(64), nullable=False),
        sa.Column("name", sa.String(512), nullable=False),
        sa.Column("language", sa.String(16), nullable=False),
        sa.Column("category", sa.String(32), nullable=False),
        sa.Column("provider_status", sa.String(32), nullable=False),
        sa.Column("components_digest", sa.String(64), nullable=False),
        sa.Column("body_text", sa.Text(), nullable=True),
        sa.Column("body_parameter_count", sa.Integer(), nullable=False),
        sa.Column("header_parameter_count", sa.Integer(), nullable=False),
        sa.Column("supported", sa.Boolean(), nullable=False),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "components_digest ~ '^[0-9a-f]{64}$'", name=op.f("ck_provider_templates_components_digest_format")
        ),
        sa.CheckConstraint(
            "body_parameter_count >= 0 AND header_parameter_count >= 0",
            name=op.f("ck_provider_templates_parameter_counts"),
        ),
        _fk(["provider_connection_id"], "provider_connections", "fk_provider_templates_org_connection"),
        sa.UniqueConstraint("provider_connection_id", "template_id", name="uq_provider_templates_template"),
        *_base("provider_templates"),
    )
    op.create_table(
        "provider_test_recipients",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("provider_connection_id", sa.Uuid(), nullable=False),
        sa.Column("label", sa.String(80), nullable=False),
        sa.Column("key_id", sa.String(16), nullable=False),
        sa.Column("address_digest", sa.String(64), nullable=False),
        sa.Column("address_hint", sa.String(40), nullable=False),
        sa.Column("consent_statement", sa.Text(), nullable=False),
        sa.Column("consented_by", sa.Uuid(), nullable=False),
        sa.Column("consented_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.CheckConstraint("status IN ('active', 'revoked')", name=op.f("ck_provider_test_recipients_status")),
        sa.CheckConstraint("address_digest ~ '^[0-9a-f]{64}$'", name=op.f("ck_provider_test_recipients_digest_format")),
        sa.CheckConstraint(
            "char_length(consent_statement) BETWEEN 20 AND 500", name=op.f("ck_provider_test_recipients_consent_length")
        ),
        sa.CheckConstraint("version >= 1", name=op.f("ck_provider_test_recipients_version_positive")),
        _fk(["provider_connection_id"], "provider_connections", "fk_provider_test_recipients_org_connection"),
        _fk(["consented_by"], "users", "fk_provider_test_recipients_org_consenter"),
        sa.UniqueConstraint("provider_connection_id", "key_id", "address_digest", name="uq_provider_test_recipients"),
        *_base("provider_test_recipients"),
    )
    op.create_table(
        "provider_test_sends",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("provider_connection_id", sa.Uuid(), nullable=False),
        sa.Column("connection_version", sa.Integer(), nullable=False),
        sa.Column("recipient_id", sa.Uuid(), nullable=False),
        sa.Column("template_row_id", sa.Uuid(), nullable=False),
        sa.Column("template_name", sa.String(512), nullable=False),
        sa.Column("template_language", sa.String(16), nullable=False),
        sa.Column("template_category", sa.String(32), nullable=False),
        sa.Column("components_digest", sa.String(64), nullable=False),
        sa.Column("params_json", postgresql.JSONB(), nullable=False),
        sa.Column("preview_digest", sa.String(64), nullable=False),
        sa.Column("nonce_digest", sa.String(64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("state", sa.String(24), nullable=False),
        sa.Column("denial_reason", sa.String(64), nullable=True),
        sa.Column("provider_message_id", sa.String(256), nullable=True),
        sa.Column("provider_message_status", sa.String(40), nullable=True),
        sa.Column("error_class", sa.String(40), nullable=True),
        sa.Column("provider_error_code", sa.String(16), nullable=True),
        sa.Column("policy_revision", sa.String(40), nullable=False),
        sa.Column("requested_by", sa.Uuid(), nullable=False),
        sa.Column("confirmed_by", sa.Uuid(), nullable=True),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("idempotency_key", sa.String(100), nullable=False),
        sa.Column("request_digest", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.CheckConstraint(f"state IN ({STATES})", name=op.f("ck_provider_test_sends_state")),
        sa.CheckConstraint(
            "preview_digest ~ '^[0-9a-f]{64}$' AND nonce_digest ~ '^[0-9a-f]{64}$'"
            " AND request_digest ~ '^[0-9a-f]{64}$'",
            name=op.f("ck_provider_test_sends_digest_formats"),
        ),
        sa.CheckConstraint(
            "state NOT IN ('reserved', 'provider_accepted', 'definitively_rejected', 'indeterminate')"
            " OR (confirmed_by IS NOT NULL AND confirmed_at IS NOT NULL)",
            name=op.f("ck_provider_test_sends_sent_only_after_confirmation"),
        ),
        sa.CheckConstraint(
            "(state = 'provider_accepted') = (provider_message_id IS NOT NULL)",
            name=op.f("ck_provider_test_sends_wamid_only_when_accepted"),
        ),
        sa.CheckConstraint("version >= 1", name=op.f("ck_provider_test_sends_version_positive")),
        _fk(["provider_connection_id"], "provider_connections", "fk_provider_test_sends_org_connection"),
        _fk(["recipient_id"], "provider_test_recipients", "fk_provider_test_sends_org_recipient"),
        _fk(["template_row_id"], "provider_templates", "fk_provider_test_sends_org_template"),
        _fk(["requested_by"], "users", "fk_provider_test_sends_org_requester"),
        _fk(["confirmed_by"], "users", "fk_provider_test_sends_org_confirmer"),
        sa.UniqueConstraint("organization_id", "idempotency_key", name="uq_provider_test_sends_idempotency"),
        *_base("provider_test_sends"),
    )
    op.create_index(
        "uq_provider_test_sends_in_flight",
        "provider_test_sends",
        ["provider_connection_id"],
        unique=True,
        postgresql_where=sa.text("state = 'reserved'"),
    )


def downgrade() -> None:
    # Test-send attempts (including uncertain ones) are audit evidence: export first on data-bearing databases.
    op.drop_index("uq_provider_test_sends_in_flight", table_name="provider_test_sends")
    op.drop_table("provider_test_sends")
    op.drop_table("provider_test_recipients")
    op.drop_table("provider_templates")
