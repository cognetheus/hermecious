"""Four-axis account assessments: assessments (P3.3).

Revision ID: 0012
Revises: 0011
Create Date: 2026-10-24
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0012"
down_revision: str | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

LEVELS = "'strong', 'moderate', 'weak', 'unknown'"


def upgrade() -> None:
    op.create_table(
        "assessments",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("account_id", sa.Uuid(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("origin", sa.String(16), nullable=False),
        sa.Column("rubric_version", sa.String(40), nullable=False),
        sa.Column("input_digest", sa.String(64), nullable=False),
        sa.Column("signal_snapshot_id", sa.Uuid(), nullable=False),
        sa.Column("offer_id", sa.Uuid(), nullable=True),
        sa.Column("offer_revision_id", sa.Uuid(), nullable=True),
        sa.Column("capability_version", sa.String(80), nullable=True),
        sa.Column("customer_fit", sa.String(16), nullable=False),
        sa.Column("need_evidence", sa.String(16), nullable=False),
        sa.Column("accessibility", sa.String(16), nullable=False),
        sa.Column("delivery_fit", sa.String(16), nullable=False),
        sa.Column("decision", sa.String(16), nullable=False),
        sa.Column("channel_eligibility", sa.String(16), nullable=False),
        sa.Column("explanation_json", postgresql.JSONB(), nullable=False),
        sa.Column("questions_json", postgresql.JSONB(), nullable=False),
        sa.Column("supersedes_id", sa.Uuid(), nullable=True),
        sa.Column("override_reason", sa.Text(), nullable=True),
        sa.Column("override_evidence_ids", postgresql.JSONB(), nullable=False),
        sa.Column("changed_fields", postgresql.JSONB(), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("origin IN ('rubric', 'override')", name=op.f("ck_assessments_origin")),
        sa.CheckConstraint(
            f"customer_fit IN ({LEVELS}) AND need_evidence IN ({LEVELS}) AND accessibility IN ({LEVELS})"
            f" AND delivery_fit IN ({LEVELS})",
            name=op.f("ck_assessments_levels"),
        ),
        sa.CheckConstraint(
            "decision IN ('contact_now', 'investigate', 'nurture', 'exclude')", name=op.f("ck_assessments_decision")
        ),
        sa.CheckConstraint(
            "channel_eligibility = 'not_evaluated'", name=op.f("ck_assessments_channel_not_evaluated")
        ),
        sa.CheckConstraint("revision >= 1", name=op.f("ck_assessments_revision_positive")),
        sa.CheckConstraint("input_digest ~ '^[0-9a-f]{64}$'", name=op.f("ck_assessments_input_digest_format")),
        sa.CheckConstraint(
            "(origin = 'override') = (override_reason IS NOT NULL)", name=op.f("ck_assessments_override_has_reason")
        ),
        sa.CheckConstraint(
            "override_reason IS NULL OR char_length(override_reason) BETWEEN 3 AND 1000",
            name=op.f("ck_assessments_override_reason_length"),
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "account_id"], ["accounts.organization_id", "accounts.id"],
            name="fk_assessments_org_account",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "signal_snapshot_id"],
            ["school_signal_snapshots.organization_id", "school_signal_snapshots.id"],
            name="fk_assessments_org_snapshot",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "offer_id"], ["offers.organization_id", "offers.id"], name="fk_assessments_org_offer"
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "supersedes_id"], ["assessments.organization_id", "assessments.id"],
            name="fk_assessments_org_supersedes",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "created_by"], ["users.organization_id", "users.id"], name="fk_assessments_org_creator"
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"], ["organizations.id"], name=op.f("fk_assessments_organization_id_organizations")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_assessments")),
        sa.UniqueConstraint("organization_id", "id", name=op.f("uq_assessments_organization_id_id")),
        sa.UniqueConstraint("organization_id", "account_id", "revision", name="uq_assessments_account_revision"),
    )  # fmt: skip
    op.execute(
        "CREATE TRIGGER assessments_append_only BEFORE UPDATE OR DELETE ON assessments"
        " FOR EACH ROW EXECUTE FUNCTION hermecious_append_only()"
    )


def downgrade() -> None:
    # Assessments and overrides are decision history: export first on data-bearing databases.
    op.execute("DROP TRIGGER assessments_append_only ON assessments")
    op.drop_table("assessments")
