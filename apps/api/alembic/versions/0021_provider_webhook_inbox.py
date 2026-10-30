"""Signed WhatsApp webhook inbox: envelopes, event items, status observations and projection, inbound messages,
service windows (P5.2). Inbound and status facts only; nothing here can send.

Revision ID: 0021
Revises: 0020
Create Date: 2026-10-30
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0021"
down_revision: str | None = "0020"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

STATUSES = "'sent', 'delivered', 'read', 'failed', 'unknown'"


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
        "provider_webhook_envelopes",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("body_sha256", sa.String(64), nullable=False),
        sa.Column("parse_status", sa.String(16), nullable=False),
        sa.Column("quarantine_reason", sa.String(64), nullable=True),
        sa.Column("counts_json", postgresql.JSONB(), nullable=False),
        sa.Column("request_id", sa.String(80), nullable=True),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("provider = 'meta_whatsapp'", name=op.f("ck_provider_webhook_envelopes_provider")),
        sa.CheckConstraint(
            "parse_status IN ('accepted', 'quarantined')", name=op.f("ck_provider_webhook_envelopes_parse_status")
        ),
        sa.CheckConstraint(
            "body_sha256 ~ '^[0-9a-f]{64}$'", name=op.f("ck_provider_webhook_envelopes_body_digest_format")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_provider_webhook_envelopes")),
    )
    op.create_table(
        "provider_event_items",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("provider_connection_id", sa.Uuid(), nullable=False),
        sa.Column("envelope_id", sa.Uuid(), nullable=False),
        sa.Column("item_type", sa.String(24), nullable=False),
        sa.Column("logical_key", sa.String(64), nullable=False),
        sa.Column("provider_message_id", sa.String(256), nullable=True),
        sa.Column("provider_timestamp", sa.DateTime(timezone=True), nullable=True),
        sa.Column("normalized_json", postgresql.JSONB(), nullable=False),
        sa.Column("processing_status", sa.String(16), nullable=False),
        sa.Column("error_class", sa.String(40), nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("arrival_seq", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.CheckConstraint(
            "item_type IN ('incoming_message', 'delivery_status', 'unsupported')",
            name=op.f("ck_provider_event_items_item_type"),
        ),
        sa.CheckConstraint(
            "processing_status IN ('pending', 'processed', 'quarantined', 'failed')",
            name=op.f("ck_provider_event_items_processing_status"),
        ),
        sa.CheckConstraint("logical_key ~ '^[0-9a-f]{64}$'", name=op.f("ck_provider_event_items_logical_key_format")),
        sa.CheckConstraint("attempts >= 0", name=op.f("ck_provider_event_items_attempts")),
        _fk(["provider_connection_id"], "provider_connections", "fk_provider_event_items_org_connection"),
        sa.ForeignKeyConstraint(
            ["envelope_id"], ["provider_webhook_envelopes.id"], name="fk_provider_event_items_envelope"
        ),
        sa.UniqueConstraint("provider_connection_id", "logical_key", name="uq_provider_event_items_logical"),
        *_base("provider_event_items"),
    )
    op.create_index(
        "ix_provider_event_items_pending",
        "provider_event_items",
        ["provider_connection_id", "processing_status", "arrival_seq"],
    )
    op.create_table(
        "provider_status_observations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("provider_connection_id", sa.Uuid(), nullable=False),
        sa.Column("event_item_id", sa.Uuid(), nullable=False),
        sa.Column("provider_message_id", sa.String(256), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("error_code", sa.String(16), nullable=True),
        sa.Column("provider_timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(f"status IN ({STATUSES})", name=op.f("ck_provider_status_observations_status")),
        _fk(["provider_connection_id"], "provider_connections", "fk_provider_status_obs_org_connection"),
        _fk(["event_item_id"], "provider_event_items", "fk_provider_status_obs_org_item"),
        sa.UniqueConstraint("event_item_id", name="uq_provider_status_observations_item"),
        *_base("provider_status_observations"),
    )
    op.create_index(
        "ix_provider_status_obs_message",
        "provider_status_observations",
        ["provider_connection_id", "provider_message_id"],
    )
    op.create_table(
        "provider_message_status",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("provider_connection_id", sa.Uuid(), nullable=False),
        sa.Column("provider_message_id", sa.String(256), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("last_provider_timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("conflict", sa.Boolean(), nullable=False),
        sa.Column("conflict_reason", sa.String(64), nullable=True),
        sa.Column("observations", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.CheckConstraint(f"status IN ({STATUSES})", name=op.f("ck_provider_message_status_status")),
        sa.CheckConstraint("observations >= 1 AND version >= 1", name=op.f("ck_provider_message_status_counters")),
        _fk(["provider_connection_id"], "provider_connections", "fk_provider_message_status_org_connection"),
        sa.UniqueConstraint("provider_connection_id", "provider_message_id", name="uq_provider_message_status_wamid"),
        *_base("provider_message_status"),
    )
    op.create_table(
        "provider_inbound_messages",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("provider_connection_id", sa.Uuid(), nullable=False),
        sa.Column("event_item_id", sa.Uuid(), nullable=False),
        sa.Column("provider_message_id", sa.String(256), nullable=False),
        sa.Column("sender_key_id", sa.String(16), nullable=False),
        sa.Column("sender_digest", sa.String(64), nullable=False),
        sa.Column("sender_hint", sa.String(40), nullable=False),
        sa.Column("contact_id", sa.Uuid(), nullable=True),
        sa.Column("assignment", sa.String(16), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("text_length", sa.Integer(), nullable=True),
        sa.Column("stop_signal", sa.Boolean(), nullable=False),
        sa.Column("provider_timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "kind IN ('text', 'image', 'document', 'interactive', 'unsupported')",
            name=op.f("ck_provider_inbound_messages_kind"),
        ),
        sa.CheckConstraint(
            "assignment IN ('contact', 'unassigned')", name=op.f("ck_provider_inbound_messages_assignment")
        ),
        sa.CheckConstraint(
            "sender_digest ~ '^[0-9a-f]{64}$'", name=op.f("ck_provider_inbound_messages_sender_digest_format")
        ),
        _fk(["provider_connection_id"], "provider_connections", "fk_provider_inbound_org_connection"),
        _fk(["contact_id"], "contacts", "fk_provider_inbound_org_contact"),
        _fk(["event_item_id"], "provider_event_items", "fk_provider_inbound_org_item"),
        sa.UniqueConstraint("provider_connection_id", "provider_message_id", name="uq_provider_inbound_wamid"),
        *_base("provider_inbound_messages"),
    )
    op.create_table(
        "provider_service_windows",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("contact_id", sa.Uuid(), nullable=False),
        sa.Column("provider_connection_id", sa.Uuid(), nullable=False),
        sa.Column("last_verified_inbound_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("provider_message_id", sa.String(256), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        _fk(["contact_id"], "contacts", "fk_provider_service_windows_org_contact"),
        _fk(["provider_connection_id"], "provider_connections", "fk_provider_service_windows_org_connection"),
        sa.UniqueConstraint("organization_id", "contact_id", name="uq_provider_service_windows_contact"),
        *_base("provider_service_windows"),
    )
    for table in ("provider_status_observations", "provider_inbound_messages"):
        op.execute(
            f"CREATE TRIGGER {table}_append_only BEFORE UPDATE OR DELETE ON {table}"
            " FOR EACH ROW EXECUTE FUNCTION hermecious_append_only()"
        )


def downgrade() -> None:
    # Received provider facts are evidence: export first on data-bearing databases.
    for table in ("provider_inbound_messages", "provider_status_observations"):
        op.execute(f"DROP TRIGGER {table}_append_only ON {table}")
    op.drop_table("provider_service_windows")
    op.drop_table("provider_inbound_messages")
    op.drop_table("provider_message_status")
    op.drop_index("ix_provider_status_obs_message", table_name="provider_status_observations")
    op.drop_table("provider_status_observations")
    op.drop_index("ix_provider_event_items_pending", table_name="provider_event_items")
    op.drop_table("provider_event_items")
    op.drop_table("provider_webhook_envelopes")
