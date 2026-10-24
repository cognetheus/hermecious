"""Channel eligibility data: contacts, contact_permissions, suppression_entries, contact_commands (P4.3).

Revision ID: 0016
Revises: 0015
Create Date: 2026-10-24
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0016"
down_revision: str | None = "0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_IMMUTABLE_EVIDENCE = (
    "id, organization_id, contact_id, channel, purpose, business_name, basis, capture_method,"
    " consent_wording_version, proof_kind, proof_key_id, proof_digest, captured_at, recorded_at, expires_at,"
    " recorded_by, supersedes_id"
)


def _row(prefix: str, columns: str) -> str:
    return "ROW(" + ", ".join(f"{prefix}.{c.strip()}" for c in columns.split(",")) + ")"


def _fk(cols: list[str], target: str, name: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(["organization_id", *cols], [f"{target}.organization_id", f"{target}.id"], name=name)


def _org(table: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        ["organization_id"], ["organizations.id"], name=op.f(f"fk_{table}_organization_id_organizations")
    )


def _base(table: str) -> list[sa.Constraint]:
    return [
        sa.PrimaryKeyConstraint("id", name=op.f(f"pk_{table}")),
        sa.UniqueConstraint("organization_id", "id", name=op.f(f"uq_{table}_organization_id_id")),
        _org(table),
    ]


def upgrade() -> None:
    op.create_table(
        "contacts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("account_id", sa.Uuid(), nullable=False),
        sa.Column("channel", sa.String(16), nullable=False),
        sa.Column("role", sa.String(32), nullable=False),
        sa.Column("key_id", sa.String(16), nullable=False),
        sa.Column("address_digest", sa.String(64), nullable=False),
        sa.Column("address_hint", sa.String(40), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("channel = 'whatsapp'", name=op.f("ck_contacts_channel")),
        sa.CheckConstraint(
            "role IN ('school_office', 'admissions_office', 'accounts_office', 'principal_office')",
            name=op.f("ck_contacts_role"),
        ),
        sa.CheckConstraint("address_digest ~ '^[0-9a-f]{64}$'", name=op.f("ck_contacts_digest_format")),
        _fk(["account_id"], "accounts", "fk_contacts_org_account"),
        _fk(["created_by"], "users", "fk_contacts_org_creator"),
        sa.UniqueConstraint("organization_id", "channel", "key_id", "address_digest", name="uq_contacts_address"),
        *_base("contacts"),
    )
    op.create_index("ix_contacts_org_account", "contacts", ["organization_id", "account_id"])

    op.create_table(
        "contact_permissions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("contact_id", sa.Uuid(), nullable=False),
        sa.Column("channel", sa.String(16), nullable=False),
        sa.Column("purpose", sa.String(16), nullable=False),
        sa.Column("business_name", sa.String(120), nullable=False),
        sa.Column("basis", sa.String(32), nullable=False),
        sa.Column("capture_method", sa.String(32), nullable=False),
        sa.Column("consent_wording_version", sa.String(60), nullable=False),
        sa.Column("proof_kind", sa.String(32), nullable=False),
        sa.Column("proof_key_id", sa.String(16), nullable=False),
        sa.Column("proof_digest", sa.String(64), nullable=False),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("recorded_by", sa.Uuid(), nullable=False),
        sa.Column("reviewed_by", sa.Uuid(), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("review_reason", sa.Text(), nullable=True),
        sa.Column("effective_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_by", sa.Uuid(), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoke_reason", sa.Text(), nullable=True),
        sa.Column("supersedes_id", sa.Uuid(), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.CheckConstraint("channel = 'whatsapp'", name=op.f("ck_contact_permissions_channel")),
        sa.CheckConstraint("purpose IN ('marketing', 'utility')", name=op.f("ck_contact_permissions_purpose")),
        sa.CheckConstraint("basis = 'explicit_opt_in'", name=op.f("ck_contact_permissions_basis")),
        sa.CheckConstraint(
            "capture_method IN ('signed_paper_form', 'web_form_checkbox', 'whatsapp_opt_in_reply', 'recorded_call')",
            name=op.f("ck_contact_permissions_capture_method"),
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'verified', 'rejected', 'revoked', 'superseded')",
            name=op.f("ck_contact_permissions_status"),
        ),
        sa.CheckConstraint("proof_digest ~ '^[0-9a-f]{64}$'", name=op.f("ck_contact_permissions_proof_digest_format")),
        sa.CheckConstraint("expires_at > captured_at", name=op.f("ck_contact_permissions_expires_after_capture")),
        sa.CheckConstraint(
            "status <> 'verified' OR (reviewed_by IS NOT NULL AND reviewed_at IS NOT NULL"
            " AND effective_at IS NOT NULL AND reviewed_by <> recorded_by)",
            name=op.f("ck_contact_permissions_verified_by_another_reviewer"),
        ),
        sa.CheckConstraint(
            "status <> 'rejected' OR (reviewed_by IS NOT NULL AND review_reason IS NOT NULL)",
            name=op.f("ck_contact_permissions_rejection_reason"),
        ),
        sa.CheckConstraint(
            "status <> 'revoked' OR (revoked_by IS NOT NULL AND revoked_at IS NOT NULL AND revoke_reason IS NOT NULL)",
            name=op.f("ck_contact_permissions_revocation_reason"),
        ),
        sa.CheckConstraint("version >= 1", name=op.f("ck_contact_permissions_version_positive")),
        _fk(["contact_id"], "contacts", "fk_contact_permissions_org_contact"),
        _fk(["supersedes_id"], "contact_permissions", "fk_contact_permissions_org_supersedes"),
        _fk(["recorded_by"], "users", "fk_contact_permissions_org_recorder"),
        _fk(["reviewed_by"], "users", "fk_contact_permissions_org_reviewer"),
        _fk(["revoked_by"], "users", "fk_contact_permissions_org_revoker"),
        *_base("contact_permissions"),
    )
    op.create_index(
        "uq_contact_permissions_open",
        "contact_permissions",
        ["organization_id", "contact_id", "channel", "purpose"],
        unique=True,
        postgresql_where=sa.text("status IN ('pending', 'verified')"),
    )
    op.execute(
        f"""
        CREATE FUNCTION hermecious_contact_permission_guard() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'contact permission evidence is history and is never deleted';
            END IF;
            IF {_row("NEW", _IMMUTABLE_EVIDENCE)} IS DISTINCT FROM {_row("OLD", _IMMUTABLE_EVIDENCE)} THEN
                RAISE EXCEPTION 'contact permission evidence is immutable';
            END IF;
            IF NOT ((OLD.status = 'pending' AND NEW.status IN ('verified', 'rejected', 'revoked', 'superseded'))
                    OR (OLD.status = 'verified' AND NEW.status IN ('revoked', 'superseded'))) THEN
                RAISE EXCEPTION 'invalid contact permission transition % -> %', OLD.status, NEW.status;
            END IF;
            IF OLD.reviewed_by IS NOT NULL AND ROW(NEW.reviewed_by, NEW.reviewed_at, NEW.review_reason,
                    NEW.effective_at) IS DISTINCT FROM ROW(OLD.reviewed_by, OLD.reviewed_at, OLD.review_reason,
                    OLD.effective_at) THEN
                RAISE EXCEPTION 'a contact permission review is recorded once';
            END IF;
            IF NEW.version <> OLD.version + 1 THEN
                RAISE EXCEPTION 'contact permission version must increase by one';
            END IF;
            RETURN NEW;
        END
        $$
        """
    )
    op.execute(
        "CREATE TRIGGER contact_permissions_guard BEFORE UPDATE OR DELETE ON contact_permissions"
        " FOR EACH ROW EXECUTE FUNCTION hermecious_contact_permission_guard()"
    )

    op.create_table(
        "suppression_entries",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("channel", sa.String(16), nullable=False),
        sa.Column("key_id", sa.String(16), nullable=False),
        sa.Column("address_digest", sa.String(64), nullable=False),
        sa.Column("address_hint", sa.String(40), nullable=False),
        sa.Column("reason", sa.String(32), nullable=False),
        sa.Column("contact_id", sa.Uuid(), nullable=True),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("channel = 'whatsapp'", name=op.f("ck_suppression_entries_channel")),
        sa.CheckConstraint(
            "reason IN ('opt_out', 'complaint', 'owner_request', 'wrong_number')",
            name=op.f("ck_suppression_entries_reason"),
        ),
        sa.CheckConstraint("address_digest ~ '^[0-9a-f]{64}$'", name=op.f("ck_suppression_entries_digest_format")),
        _fk(["contact_id"], "contacts", "fk_suppression_entries_org_contact"),
        _fk(["created_by"], "users", "fk_suppression_entries_org_creator"),
        sa.UniqueConstraint("organization_id", "channel", "key_id", "address_digest", name="uq_suppression_address"),
        *_base("suppression_entries"),
    )

    op.create_table(
        "contact_commands",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("idempotency_key", sa.String(100), nullable=False),
        sa.Column("request_digest", sa.String(64), nullable=False),
        sa.Column("outcome_json", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("request_digest ~ '^[0-9a-f]{64}$'", name=op.f("ck_contact_commands_request_digest_format")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_contact_commands")),
        sa.UniqueConstraint("organization_id", "idempotency_key", name="uq_contact_commands_key"),
        _org("contact_commands"),
    )
    for table in ("contacts", "suppression_entries"):
        op.execute(
            f"CREATE TRIGGER {table}_append_only BEFORE UPDATE OR DELETE ON {table}"
            " FOR EACH ROW EXECUTE FUNCTION hermecious_append_only()"
        )


def downgrade() -> None:
    # Never silently lose an opt-out: refuse while any suppression exists (export and review first).
    op.execute(
        "DO $$ BEGIN IF EXISTS (SELECT 1 FROM suppression_entries) THEN"
        " RAISE EXCEPTION 'refusing to drop suppression_entries: suppressions exist'; END IF; END $$"
    )
    op.drop_table("contact_commands")
    op.execute("DROP TRIGGER suppression_entries_append_only ON suppression_entries")
    op.drop_table("suppression_entries")
    op.execute("DROP TRIGGER contact_permissions_guard ON contact_permissions")
    op.drop_index("uq_contact_permissions_open", table_name="contact_permissions")
    op.drop_table("contact_permissions")
    op.execute("DROP FUNCTION hermecious_contact_permission_guard()")
    op.execute("DROP TRIGGER contacts_append_only ON contacts")
    op.drop_index("ix_contacts_org_account", table_name="contacts")
    op.drop_table("contacts")
