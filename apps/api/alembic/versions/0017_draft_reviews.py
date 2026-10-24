"""Content approval: drafts.origin, draft_reviews (P4.4).

Revision ID: 0017
Revises: 0016
Create Date: 2026-10-24
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0017"
down_revision: str | None = "0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _fk(cols: list[str], target: str, name: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(["organization_id", *cols], [f"{target}.organization_id", f"{target}.id"], name=name)


def upgrade() -> None:
    # A column default does not fire the drafts append-only trigger; existing rows read as `generated`.
    op.add_column("drafts", sa.Column("origin", sa.String(16), server_default="generated", nullable=False))
    op.create_check_constraint(op.f("ck_drafts_origin"), "drafts", "origin IN ('generated', 'edited')")
    op.create_table(
        "draft_reviews",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("draft_id", sa.Uuid(), nullable=False),
        sa.Column("campaign_id", sa.Uuid(), nullable=False),
        sa.Column("account_id", sa.Uuid(), nullable=False),
        sa.Column("draft_revision", sa.Integer(), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("decision", sa.String(20), nullable=False),
        sa.Column("content_digest", sa.String(64), nullable=False),
        sa.Column("contact_id", sa.Uuid(), nullable=True),
        sa.Column("purpose", sa.String(16), nullable=True),
        sa.Column("template_ref", sa.String(80), nullable=True),
        sa.Column("eligibility_decision", sa.String(24), nullable=True),
        sa.Column("simulation_only", sa.Boolean(), nullable=False),
        sa.Column("version_vector", postgresql.JSONB(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("reviewer_id", sa.Uuid(), nullable=False),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revokes_id", sa.Uuid(), nullable=True),
        sa.Column("idempotency_key", sa.String(100), nullable=False),
        sa.Column("request_digest", sa.String(64), nullable=False),
        sa.CheckConstraint(
            "decision IN ('approved_content', 'rejected', 'revoked')", name=op.f("ck_draft_reviews_decision")
        ),
        sa.CheckConstraint("simulation_only", name=op.f("ck_draft_reviews_simulation_only")),
        sa.CheckConstraint("content_digest ~ '^[0-9a-f]{64}$'", name=op.f("ck_draft_reviews_content_digest_format")),
        sa.CheckConstraint("request_digest ~ '^[0-9a-f]{64}$'", name=op.f("ck_draft_reviews_request_digest_format")),
        sa.CheckConstraint("char_length(reason) BETWEEN 3 AND 500", name=op.f("ck_draft_reviews_reason_length")),
        sa.CheckConstraint("seq >= 1", name=op.f("ck_draft_reviews_seq_positive")),
        sa.CheckConstraint(
            "decision <> 'approved_content' OR (contact_id IS NOT NULL AND purpose IS NOT NULL"
            " AND template_ref IS NOT NULL AND expires_at IS NOT NULL"
            " AND eligibility_decision IN ('allow_for_simulation', 'defer'))",
            name=op.f("ck_draft_reviews_approval_binding"),
        ),
        sa.CheckConstraint(
            "(decision = 'revoked') = (revokes_id IS NOT NULL)", name=op.f("ck_draft_reviews_revocation_target")
        ),
        _fk(["draft_id"], "drafts", "fk_draft_reviews_org_draft"),
        _fk(["campaign_id"], "campaigns", "fk_draft_reviews_org_campaign"),
        _fk(["account_id"], "accounts", "fk_draft_reviews_org_account"),
        _fk(["contact_id"], "contacts", "fk_draft_reviews_org_contact"),
        _fk(["reviewer_id"], "users", "fk_draft_reviews_org_reviewer"),
        _fk(["revokes_id"], "draft_reviews", "fk_draft_reviews_org_revokes"),
        sa.ForeignKeyConstraint(
            ["organization_id"], ["organizations.id"], name=op.f("fk_draft_reviews_organization_id_organizations")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_draft_reviews")),
        sa.UniqueConstraint("organization_id", "id", name=op.f("uq_draft_reviews_organization_id_id")),
        sa.UniqueConstraint("organization_id", "draft_id", "seq", name="uq_draft_reviews_seq"),
        sa.UniqueConstraint("organization_id", "idempotency_key", name="uq_draft_reviews_idempotency"),
    )
    op.execute(
        "CREATE TRIGGER draft_reviews_append_only BEFORE UPDATE OR DELETE ON draft_reviews"
        " FOR EACH ROW EXECUTE FUNCTION hermecious_append_only()"
    )


def downgrade() -> None:
    # Review receipts are history: export first on data-bearing databases.
    op.execute("DROP TRIGGER draft_reviews_append_only ON draft_reviews")
    op.drop_table("draft_reviews")
    op.drop_constraint(op.f("ck_drafts_origin"), "drafts", type_="check")
    op.drop_column("drafts", "origin")
