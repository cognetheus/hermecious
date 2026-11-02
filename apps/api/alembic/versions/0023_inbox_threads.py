"""Read-only WhatsApp inbox threads (P5.4).

Revision ID: 0023
Revises: 0022
Create Date: 2026-11-02
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0023"
down_revision: str | None = "0022"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "inbox_threads",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("provider_connection_id", sa.Uuid(), nullable=False),
        sa.Column("party_key_id", sa.String(16), nullable=False),
        sa.Column("party_digest", sa.String(64), nullable=False),
        sa.Column("party_hint", sa.String(40), nullable=False),
        sa.Column("last_activity_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_inbound_seq", sa.BigInteger(), nullable=False),
        sa.Column("reviewed_through_seq", sa.BigInteger(), nullable=False),
        sa.Column("reviewed_by", sa.Uuid(), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.CheckConstraint("party_digest ~ '^[0-9a-f]{64}$'", name=op.f("ck_inbox_threads_party_digest_format")),
        sa.CheckConstraint(
            "reviewed_through_seq <= last_inbound_seq", name=op.f("ck_inbox_threads_reviewed_not_ahead")
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "provider_connection_id"],
            ["provider_connections.organization_id", "provider_connections.id"],
            name="fk_inbox_threads_org_connection",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"], ["organizations.id"], name=op.f("fk_inbox_threads_organization_id_organizations")
        ),
        sa.ForeignKeyConstraint(["reviewed_by"], ["users.id"], name=op.f("fk_inbox_threads_reviewed_by_users")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_inbox_threads")),
        sa.UniqueConstraint("organization_id", "id", name=op.f("uq_inbox_threads_organization_id_id")),
        sa.UniqueConstraint("provider_connection_id", "party_key_id", "party_digest", name="uq_inbox_threads_party"),
    )
    op.create_index("ix_inbox_threads_activity", "inbox_threads", ["organization_id", "last_activity_at", "id"])
    op.create_index(
        "ix_provider_inbound_party",
        "provider_inbound_messages",
        ["provider_connection_id", "sender_key_id", "sender_digest"],
    )


def downgrade() -> None:
    # Threads are a derived projection (rebuildable from the signed source tables); nothing is lost by dropping them.
    op.drop_index("ix_provider_inbound_party", table_name="provider_inbound_messages")
    op.drop_index("ix_inbox_threads_activity", table_name="inbox_threads")
    op.drop_table("inbox_threads")
