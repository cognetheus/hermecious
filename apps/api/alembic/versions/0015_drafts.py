"""Immutable first-contact draft revisions: drafts (P4.2).

Revision ID: 0015
Revises: 0014
Create Date: 2026-10-24
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0015"
down_revision: str | None = "0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _fk(cols: list[str], target: str, name: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(["organization_id", *cols], [f"{target}.organization_id", f"{target}.id"], name=name)


def upgrade() -> None:
    op.create_table(
        "drafts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("campaign_id", sa.Uuid(), nullable=False),
        sa.Column("account_id", sa.Uuid(), nullable=False),
        sa.Column("membership_id", sa.Uuid(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("mode", sa.String(16), nullable=False),
        sa.Column("template_id", sa.String(60), nullable=False),
        sa.Column("locale", sa.String(16), nullable=False),
        sa.Column("contract_version", sa.String(40), nullable=False),
        sa.Column("body_text", sa.Text(), nullable=False),
        sa.Column("sentences_json", postgresql.JSONB(), nullable=False),
        sa.Column("assessment_id", sa.Uuid(), nullable=False),
        sa.Column("assessment_revision", sa.Integer(), nullable=False),
        sa.Column("offer_id", sa.Uuid(), nullable=False),
        sa.Column("offer_revision_id", sa.Uuid(), nullable=False),
        sa.Column("capability_version", sa.String(80), nullable=False),
        sa.Column("signal_snapshot_id", sa.Uuid(), nullable=True),
        sa.Column("fact_ids", postgresql.JSONB(), nullable=False),
        sa.Column("source_policy_versions", postgresql.JSONB(), nullable=False),
        sa.Column("fingerprint", sa.String(64), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("operator_review_required", sa.Boolean(), nullable=False),
        sa.Column("sendable", sa.Boolean(), nullable=False),
        sa.Column("channel_eligibility", sa.String(16), nullable=False),
        sa.Column("idempotency_key", sa.String(100), nullable=False),
        sa.Column("request_digest", sa.String(64), nullable=False),
        sa.Column("regenerated_from", sa.Uuid(), nullable=True),
        sa.Column("regenerate_reason", sa.Text(), nullable=True),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("status = 'needs_review'", name=op.f("ck_drafts_stored_status")),
        sa.CheckConstraint("operator_review_required", name=op.f("ck_drafts_review_required")),
        sa.CheckConstraint("NOT sendable", name=op.f("ck_drafts_never_sendable")),
        sa.CheckConstraint("channel_eligibility = 'not_evaluated'", name=op.f("ck_drafts_channel_not_evaluated")),
        sa.CheckConstraint("char_length(body_text) <= 650", name=op.f("ck_drafts_body_length")),
        sa.CheckConstraint("fingerprint ~ '^[0-9a-f]{64}$'", name=op.f("ck_drafts_fingerprint_format")),
        sa.CheckConstraint("request_digest ~ '^[0-9a-f]{64}$'", name=op.f("ck_drafts_request_digest_format")),
        sa.CheckConstraint(
            "(regenerated_from IS NULL) = (regenerate_reason IS NULL)", name=op.f("ck_drafts_regeneration_reason")
        ),
        sa.CheckConstraint("revision >= 1", name=op.f("ck_drafts_revision_positive")),
        _fk(["campaign_id"], "campaigns", "fk_drafts_org_campaign"),
        _fk(["account_id"], "accounts", "fk_drafts_org_account"),
        _fk(["membership_id"], "campaign_accounts", "fk_drafts_org_membership"),
        _fk(["assessment_id"], "assessments", "fk_drafts_org_assessment"),
        _fk(["regenerated_from"], "drafts", "fk_drafts_org_previous"),
        sa.ForeignKeyConstraint(
            ["organization_id", "created_by"], ["users.organization_id", "users.id"], name="fk_drafts_org_creator"
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"], ["organizations.id"], name=op.f("fk_drafts_organization_id_organizations")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_drafts")),
        sa.UniqueConstraint("organization_id", "id", name=op.f("uq_drafts_organization_id_id")),
        sa.UniqueConstraint("organization_id", "idempotency_key", name="uq_drafts_idempotency"),
        sa.UniqueConstraint("organization_id", "campaign_id", "account_id", "revision", name="uq_drafts_revision"),
    )
    op.execute(
        "CREATE TRIGGER drafts_append_only BEFORE UPDATE OR DELETE ON drafts"
        " FOR EACH ROW EXECUTE FUNCTION hermecious_append_only()"
    )


def downgrade() -> None:
    # Drafts are review history: export first on data-bearing databases.
    op.execute("DROP TRIGGER drafts_append_only ON drafts")
    op.drop_table("drafts")
