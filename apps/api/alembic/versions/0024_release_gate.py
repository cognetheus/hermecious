"""Production readiness, owner attestations, pilot authorizations and pilot sends (P5.5).

Revision ID: 0024
Revises: 0023
Create Date: 2026-11-02
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0024"
down_revision: str | None = "0023"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

KINDS = "'meta_business_verification', 'pakistan_legal_review', 'real_test_receipt', 'operations_readiness'"
STATES = (
    "'awaiting_confirmation', 'reserved', 'provider_accepted', 'definitively_rejected', 'indeterminate', 'denied',"
    " 'expired', 'cancelled'"
)
APPEND_ONLY = ("readiness_attestations", "readiness_assessments")


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


def _user(table: str, column: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint([column], ["users.id"], name=op.f(f"fk_{table}_{column}_users"))


def upgrade() -> None:
    op.create_table(
        "readiness_attestations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(40), nullable=False),
        sa.Column("statement", sa.Text(), nullable=False),
        sa.Column("evidence_ref", sa.String(500), nullable=False),
        sa.Column("attested_by", sa.Uuid(), nullable=False),
        sa.Column("attested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(f"kind IN ({KINDS})", name=op.f("ck_readiness_attestations_kind")),
        sa.CheckConstraint(
            "char_length(evidence_ref) BETWEEN 10 AND 500", name=op.f("ck_readiness_attestations_evidence_ref_length")
        ),
        sa.CheckConstraint(
            "char_length(statement) BETWEEN 20 AND 1000", name=op.f("ck_readiness_attestations_statement_length")
        ),
        sa.CheckConstraint("expires_at > attested_at", name=op.f("ck_readiness_attestations_expires_after")),
        _user("readiness_attestations", "attested_by"),
        *_base("readiness_attestations"),
    )
    op.create_index(
        "ix_readiness_attestations_kind", "readiness_attestations", ["organization_id", "kind", "attested_at"]
    )
    op.create_table(
        "readiness_assessments",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("snapshot_version", sa.String(32), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("digest", sa.String(64), nullable=False),
        sa.Column("checks_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("identity_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("environment", sa.String(16), nullable=False),
        sa.Column("build_sha", sa.String(40), nullable=True),
        sa.Column("checked_by", sa.Uuid(), nullable=False),
        sa.Column("checked_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('no_go', 'blocked_external', 'ready_for_operator_review')",
            name=op.f("ck_readiness_assessments_status"),
        ),
        sa.CheckConstraint("digest ~ '^[0-9a-f]{64}$'", name=op.f("ck_readiness_assessments_digest_format")),
        sa.CheckConstraint("expires_at > checked_at", name=op.f("ck_readiness_assessments_expires_after")),
        _user("readiness_assessments", "checked_by"),
        *_base("readiness_assessments"),
    )
    op.create_index("ix_readiness_assessments_recent", "readiness_assessments", ["organization_id", "checked_at"])
    op.create_table(
        "pilot_authorizations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("provider_connection_id", sa.Uuid(), nullable=False),
        sa.Column("assessment_id", sa.Uuid(), nullable=False),
        sa.Column("assessment_digest", sa.String(64), nullable=False),
        sa.Column("purpose", sa.String(16), nullable=False),
        sa.Column("max_per_day", sa.Integer(), nullable=False),
        sa.Column("acknowledgement", sa.Text(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("pause_reason", sa.String(40), nullable=True),
        sa.Column("authorized_by", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.CheckConstraint("status IN ('active', 'paused', 'revoked')", name=op.f("ck_pilot_authorizations_status")),
        sa.CheckConstraint("purpose IN ('marketing', 'utility')", name=op.f("ck_pilot_authorizations_purpose")),
        sa.CheckConstraint("max_per_day BETWEEN 1 AND 3", name=op.f("ck_pilot_authorizations_max_per_day_range")),
        sa.CheckConstraint("expires_at > created_at", name=op.f("ck_pilot_authorizations_expires_after")),
        sa.CheckConstraint(
            "expires_at <= created_at + interval '14 days'",
            name=op.f("ck_pilot_authorizations_expires_within_14_days"),
        ),
        sa.CheckConstraint(
            "assessment_digest ~ '^[0-9a-f]{64}$'", name=op.f("ck_pilot_authorizations_assessment_digest_format")
        ),
        _fk(["provider_connection_id"], "provider_connections", "fk_pilot_authorizations_org_connection"),
        _fk(["assessment_id"], "readiness_assessments", "fk_pilot_authorizations_org_assessment"),
        _user("pilot_authorizations", "authorized_by"),
        *_base("pilot_authorizations"),
    )
    op.create_index(
        "uq_pilot_authorizations_live",
        "pilot_authorizations",
        ["provider_connection_id"],
        unique=True,
        postgresql_where=sa.text("status IN ('active', 'paused')"),
    )
    op.create_table(
        "pilot_sends",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("authorization_id", sa.Uuid(), nullable=False),
        sa.Column("provider_connection_id", sa.Uuid(), nullable=False),
        sa.Column("contact_id", sa.Uuid(), nullable=False),
        sa.Column("draft_id", sa.Uuid(), nullable=False),
        sa.Column("draft_revision", sa.Integer(), nullable=False),
        sa.Column("approval_id", sa.Uuid(), nullable=False),
        sa.Column("template_row_id", sa.Uuid(), nullable=False),
        sa.Column("template_name", sa.String(512), nullable=False),
        sa.Column("template_language", sa.String(16), nullable=False),
        sa.Column("template_category", sa.String(32), nullable=False),
        sa.Column("components_digest", sa.String(64), nullable=False),
        sa.Column("params_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("purpose", sa.String(16), nullable=False),
        sa.Column("preview_digest", sa.String(64), nullable=False),
        sa.Column("nonce_digest", sa.String(64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("state", sa.String(24), nullable=False),
        sa.Column("denial_reason", sa.String(80), nullable=True),
        sa.Column("provider_message_id", sa.String(256), nullable=True),
        sa.Column("provider_message_status", sa.String(40), nullable=True),
        sa.Column("error_class", sa.String(40), nullable=True),
        sa.Column("provider_error_code", sa.String(16), nullable=True),
        sa.Column("requested_by", sa.Uuid(), nullable=False),
        sa.Column("confirmed_by", sa.Uuid(), nullable=True),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("idempotency_key", sa.String(100), nullable=False),
        sa.Column("request_digest", sa.String(64), nullable=False),
        sa.Column("simulated_transport", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.CheckConstraint(f"state IN ({STATES})", name=op.f("ck_pilot_sends_state")),
        sa.CheckConstraint("preview_digest ~ '^[0-9a-f]{64}$'", name=op.f("ck_pilot_sends_preview_digest_format")),
        sa.CheckConstraint("nonce_digest ~ '^[0-9a-f]{64}$'", name=op.f("ck_pilot_sends_nonce_digest_format")),
        sa.CheckConstraint(
            "state IN ('awaiting_confirmation', 'denied', 'expired', 'cancelled') OR confirmed_by IS NOT NULL",
            name=op.f("ck_pilot_sends_sent_only_after_confirmation"),
        ),
        sa.CheckConstraint(
            "(provider_message_id IS NULL) OR state = 'provider_accepted'",
            name=op.f("ck_pilot_sends_wamid_only_when_accepted"),
        ),
        _fk(["authorization_id"], "pilot_authorizations", "fk_pilot_sends_org_authorization"),
        _fk(["provider_connection_id"], "provider_connections", "fk_pilot_sends_org_connection"),
        _fk(["contact_id"], "contacts", "fk_pilot_sends_org_contact"),
        _fk(["draft_id"], "drafts", "fk_pilot_sends_org_draft"),
        _fk(["approval_id"], "draft_reviews", "fk_pilot_sends_org_approval"),
        _fk(["template_row_id"], "provider_templates", "fk_pilot_sends_org_template"),
        _user("pilot_sends", "requested_by"),
        _user("pilot_sends", "confirmed_by"),
        sa.UniqueConstraint("organization_id", "idempotency_key", name="uq_pilot_sends_idempotency"),
        *_base("pilot_sends"),
    )
    op.create_index(
        "uq_pilot_sends_in_flight",
        "pilot_sends",
        ["provider_connection_id"],
        unique=True,
        postgresql_where=sa.text("state = 'reserved'"),
    )
    for table in APPEND_ONLY:
        op.execute(
            f"CREATE TRIGGER {table}_append_only BEFORE UPDATE OR DELETE ON {table}"
            " FOR EACH ROW EXECUTE FUNCTION hermecious_append_only()"
        )


def downgrade() -> None:
    # Assessments, attestations and pilot attempts are audit evidence: export first on data-bearing databases.
    for table in APPEND_ONLY:
        op.execute(f"DROP TRIGGER {table}_append_only ON {table}")
    op.drop_index("uq_pilot_sends_in_flight", table_name="pilot_sends")
    op.drop_table("pilot_sends")
    op.drop_index("uq_pilot_authorizations_live", table_name="pilot_authorizations")
    op.drop_table("pilot_authorizations")
    op.drop_index("ix_readiness_assessments_recent", table_name="readiness_assessments")
    op.drop_table("readiness_assessments")
    op.drop_index("ix_readiness_attestations_kind", table_name="readiness_attestations")
    op.drop_table("readiness_attestations")
