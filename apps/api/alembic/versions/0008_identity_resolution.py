"""Campus identity review: identity_suggestions, candidate_account_links, identity_decisions (P2.3).

Revision ID: 0008
Revises: 0007
Create Date: 2026-10-24
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

STATUSES = "'pending', 'confirmed', 'distinct', 'deferred', 'superseded', 'undone', 'reallocation_review'"


def upgrade() -> None:
    op.create_table(
        "identity_suggestions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("left_candidate_id", sa.Uuid(), nullable=False),
        sa.Column("right_candidate_id", sa.Uuid(), nullable=True),
        sa.Column("existing_account_id", sa.Uuid(), nullable=True),
        sa.Column("algorithm_version", sa.String(40), nullable=False),
        sa.Column("resolution", sa.String(32), nullable=False),
        sa.Column("reason_codes", postgresql.JSONB(), nullable=False),
        sa.Column("features", postgresql.JSONB(), nullable=False),
        sa.Column("evidence_source_record_ids", postgresql.JSONB(), nullable=False),
        sa.Column("left_revision", sa.Integer(), nullable=False),
        sa.Column("right_revision", sa.Integer(), nullable=True),
        sa.Column("evidence_changed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("reviewer_user_id", sa.Uuid(), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("decision_reason", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "(right_candidate_id IS NULL) <> (existing_account_id IS NULL)",
            name=op.f("ck_identity_suggestions_exactly_one_counterpart"),
        ),
        sa.CheckConstraint(
            "right_candidate_id IS NULL OR left_candidate_id < right_candidate_id",
            name=op.f("ck_identity_suggestions_canonical_order"),
        ),
        sa.CheckConstraint(
            "resolution IN ('suggest_review', 'insufficient_evidence')", name=op.f("ck_identity_suggestions_resolution")
        ),
        sa.CheckConstraint(f"status IN ({STATUSES})", name=op.f("ck_identity_suggestions_status")),
        sa.CheckConstraint("version >= 1", name=op.f("ck_identity_suggestions_version_positive")),
        sa.ForeignKeyConstraint(
            ["organization_id", "left_candidate_id"],
            ["discovery_candidates.organization_id", "discovery_candidates.id"],
            name="fk_identity_suggestions_org_left",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "right_candidate_id"],
            ["discovery_candidates.organization_id", "discovery_candidates.id"],
            name="fk_identity_suggestions_org_right",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "existing_account_id"],
            ["accounts.organization_id", "accounts.id"],
            name="fk_identity_suggestions_org_account",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "reviewer_user_id"],
            ["users.organization_id", "users.id"],
            name="fk_identity_suggestions_org_reviewer",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("fk_identity_suggestions_organization_id_organizations"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_identity_suggestions")),
        sa.UniqueConstraint("organization_id", "id", name=op.f("uq_identity_suggestions_organization_id_id")),
    )
    op.create_index(
        "uq_identity_suggestions_candidate_pair",
        "identity_suggestions",
        ["organization_id", "left_candidate_id", "right_candidate_id", "algorithm_version"],
        unique=True,
        postgresql_where=sa.text("right_candidate_id IS NOT NULL"),
    )
    op.create_index(
        "uq_identity_suggestions_candidate_account",
        "identity_suggestions",
        ["organization_id", "left_candidate_id", "existing_account_id", "algorithm_version"],
        unique=True,
        postgresql_where=sa.text("existing_account_id IS NOT NULL"),
    )
    op.create_index(
        "ix_identity_suggestions_org_status_created",
        "identity_suggestions",
        ["organization_id", "status", "created_at", "id"],
    )

    op.create_table(
        "candidate_account_links",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("candidate_id", sa.Uuid(), nullable=False),
        sa.Column("account_id", sa.Uuid(), nullable=False),
        sa.Column("suggestion_id", sa.Uuid(), nullable=True),
        sa.Column("linked_by", sa.Uuid(), nullable=False),
        sa.Column("linked_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("unlinked_by", sa.Uuid(), nullable=True),
        sa.Column("unlinked_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "(unlinked_at IS NULL) = (unlinked_by IS NULL)", name=op.f("ck_candidate_account_links_unlink_complete")
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "candidate_id"],
            ["discovery_candidates.organization_id", "discovery_candidates.id"],
            name="fk_candidate_account_links_org_candidate",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "account_id"],
            ["accounts.organization_id", "accounts.id"],
            name="fk_candidate_account_links_org_account",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "suggestion_id"],
            ["identity_suggestions.organization_id", "identity_suggestions.id"],
            name="fk_candidate_account_links_org_suggestion",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "linked_by"], ["users.organization_id", "users.id"], name="fk_cal_org_linked_by"
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "unlinked_by"], ["users.organization_id", "users.id"], name="fk_cal_org_unlinked_by"
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("fk_candidate_account_links_organization_id_organizations"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_candidate_account_links")),
        sa.UniqueConstraint("organization_id", "id", name=op.f("uq_candidate_account_links_organization_id_id")),
    )
    op.create_index(
        "uq_candidate_account_links_active",
        "candidate_account_links",
        ["organization_id", "candidate_id"],
        unique=True,
        postgresql_where=sa.text("unlinked_at IS NULL"),
    )

    op.create_table(
        "identity_decisions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("suggestion_id", sa.Uuid(), nullable=False),
        sa.Column("command_id", sa.Uuid(), nullable=False),
        sa.Column("action", sa.String(32), nullable=False),
        sa.Column("actor_user_id", sa.Uuid(), nullable=False),
        sa.Column("prior_status", sa.String(24), nullable=False),
        sa.Column("next_status", sa.String(24), nullable=False),
        sa.Column("expected_version", sa.Integer(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("payload_digest", sa.String(64), nullable=False),
        sa.Column("held_fact_ids", postgresql.JSONB(), nullable=False),
        sa.Column("link_id", sa.Uuid(), nullable=True),
        sa.Column("reverses_decision_id", sa.Uuid(), nullable=True),
        sa.Column("request_id", sa.String(64), nullable=True),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "action IN ('confirm_same_campus', 'mark_distinct', 'defer', 'undo')",
            name=op.f("ck_identity_decisions_action"),
        ),
        sa.CheckConstraint("char_length(reason) BETWEEN 3 AND 1000", name=op.f("ck_identity_decisions_reason_length")),
        sa.CheckConstraint(
            "payload_digest ~ '^[0-9a-f]{64}$'", name=op.f("ck_identity_decisions_payload_digest_format")
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "suggestion_id"],
            ["identity_suggestions.organization_id", "identity_suggestions.id"],
            name="fk_identity_decisions_org_suggestion",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "actor_user_id"],
            ["users.organization_id", "users.id"],
            name="fk_identity_decisions_org_actor",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "reverses_decision_id"],
            ["identity_decisions.organization_id", "identity_decisions.id"],
            name="fk_identity_decisions_org_reverses",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"], ["organizations.id"], name=op.f("fk_identity_decisions_organization_id_organizations")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_identity_decisions")),
        sa.UniqueConstraint(
            "organization_id", "command_id", name=op.f("uq_identity_decisions_organization_id_command_id")
        ),
        sa.UniqueConstraint("organization_id", "id", name=op.f("uq_identity_decisions_organization_id_id")),
    )
    op.create_index(
        "ix_identity_decisions_org_suggestion",
        "identity_decisions",
        ["organization_id", "suggestion_id", "recorded_at"],
    )
    # Reuses the P1.4 append-only guard function.
    op.execute(
        "CREATE TRIGGER identity_decisions_append_only BEFORE UPDATE OR DELETE ON identity_decisions"
        " FOR EACH ROW EXECUTE FUNCTION hermecious_append_only()"
    )


def downgrade() -> None:
    # Decisions are review history: on data-bearing databases export first and prefer a forward repair.
    op.execute("DROP TRIGGER identity_decisions_append_only ON identity_decisions")
    op.drop_index("ix_identity_decisions_org_suggestion", table_name="identity_decisions")
    op.drop_table("identity_decisions")
    op.drop_index("uq_candidate_account_links_active", table_name="candidate_account_links")
    op.drop_table("candidate_account_links")
    op.drop_index("ix_identity_suggestions_org_status_created", table_name="identity_suggestions")
    op.drop_index("uq_identity_suggestions_candidate_account", table_name="identity_suggestions")
    op.drop_index("uq_identity_suggestions_candidate_pair", table_name="identity_suggestions")
    op.drop_table("identity_suggestions")
