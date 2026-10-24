"""Discovery runs and reviewer decisions: discovery_runs, discovery_run_candidates, discovery_review_decisions (P2.4).

Revision ID: 0009
Revises: 0008
Create Date: 2026-10-24
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "discovery_runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        sa.Column("vertical_slug", sa.String(80), nullable=False),
        sa.Column("city", sa.String(120), nullable=False),
        sa.Column("area_label", sa.String(300), nullable=False),
        sa.Column("provider", sa.String(100), nullable=False),
        sa.Column("adapter_version", sa.String(40), nullable=False),
        sa.Column("rights_policy_version", sa.String(80), nullable=False),
        sa.Column("attribution", sa.String(300), nullable=True),
        sa.Column("budget_json", postgresql.JSONB(), nullable=False),
        sa.Column("usage_json", postgresql.JSONB(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("examined_count", sa.Integer(), nullable=False),
        sa.Column("staged_count", sa.Integer(), nullable=False),
        sa.Column("rejected_count", sa.Integer(), nullable=False),
        sa.Column("displayed_count", sa.Integer(), nullable=False),
        sa.Column("truncated", sa.Boolean(), nullable=False),
        sa.Column("stop_reason", sa.String(40), nullable=True),
        sa.Column("partial_reason", sa.String(80), nullable=True),
        sa.Column("error_code", sa.String(80), nullable=True),
        sa.Column("idempotency_key", sa.String(100), nullable=False),
        sa.Column("request_digest", sa.String(64), nullable=False),
        sa.Column("job_id", sa.Uuid(), nullable=True),
        sa.Column("requested_cancel_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('pending', 'running', 'completed', 'partial', 'failed', 'cancelled')",
            name=op.f("ck_discovery_runs_status"),
        ),
        sa.CheckConstraint(
            "idempotency_key ~ '^[A-Za-z0-9._:-]{8,100}$'", name=op.f("ck_discovery_runs_idempotency_key_format")
        ),
        sa.CheckConstraint("request_digest ~ '^[0-9a-f]{64}$'", name=op.f("ck_discovery_runs_request_digest_format")),
        sa.CheckConstraint(
            "examined_count >= 0 AND staged_count >= 0 AND rejected_count >= 0 AND displayed_count BETWEEN 0 AND 30",
            name=op.f("ck_discovery_runs_counts"),
        ),
        sa.CheckConstraint(
            "status NOT IN ('completed', 'partial', 'failed', 'cancelled') OR finished_at IS NOT NULL",
            name=op.f("ck_discovery_runs_terminal_has_finish"),
        ),
        sa.CheckConstraint("version >= 1", name=op.f("ck_discovery_runs_version_positive")),
        sa.ForeignKeyConstraint(
            ["organization_id", "created_by"],
            ["users.organization_id", "users.id"],
            name="fk_discovery_runs_org_creator",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "job_id"], ["jobs.organization_id", "jobs.id"], name="fk_discovery_runs_org_job"
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"], ["organizations.id"], name=op.f("fk_discovery_runs_organization_id_organizations")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_discovery_runs")),
        sa.UniqueConstraint("organization_id", "id", name=op.f("uq_discovery_runs_organization_id_id")),
        sa.UniqueConstraint(
            "organization_id", "idempotency_key", name=op.f("uq_discovery_runs_organization_id_idempotency_key")
        ),
    )
    op.create_index("ix_discovery_runs_org_created", "discovery_runs", ["organization_id", "created_at", "id"])

    op.create_table(
        "discovery_run_candidates",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("candidate_id", sa.Uuid(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("display_status", sa.String(16), nullable=False),
        sa.Column("account_id", sa.Uuid(), nullable=True),
        sa.Column("review_note", sa.Text(), nullable=True),
        sa.Column("reviewed_by", sa.Uuid(), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "display_status IN ('pending', 'accepted', 'rejected', 'deferred')",
            name=op.f("ck_discovery_run_candidates_display_status"),
        ),
        sa.CheckConstraint(
            "display_status <> 'accepted' OR account_id IS NOT NULL",
            name=op.f("ck_discovery_run_candidates_accepted_has_account"),
        ),
        sa.CheckConstraint("version >= 1", name=op.f("ck_discovery_run_candidates_version_positive")),
        sa.ForeignKeyConstraint(
            ["organization_id", "run_id"],
            ["discovery_runs.organization_id", "discovery_runs.id"],
            name="fk_drc_org_run",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "candidate_id"],
            ["discovery_candidates.organization_id", "discovery_candidates.id"],
            name="fk_drc_org_candidate",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "account_id"], ["accounts.organization_id", "accounts.id"], name="fk_drc_org_account"
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "reviewed_by"], ["users.organization_id", "users.id"], name="fk_drc_org_reviewer"
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("fk_discovery_run_candidates_organization_id_organizations"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_discovery_run_candidates")),
        sa.UniqueConstraint(
            "organization_id",
            "run_id",
            "candidate_id",
            name=op.f("uq_discovery_run_candidates_organization_id_run_id_candidate_id"),
        ),
        sa.UniqueConstraint("organization_id", "id", name=op.f("uq_discovery_run_candidates_organization_id_id")),
    )

    op.create_table(
        "discovery_review_decisions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("candidate_id", sa.Uuid(), nullable=False),
        sa.Column("idempotency_key", sa.String(100), nullable=False),
        sa.Column("action", sa.String(24), nullable=False),
        sa.Column("payload_digest", sa.String(64), nullable=False),
        sa.Column("prior_status", sa.String(16), nullable=False),
        sa.Column("next_status", sa.String(16), nullable=False),
        sa.Column("account_id", sa.Uuid(), nullable=True),
        sa.Column("converged", sa.Boolean(), nullable=False),
        sa.Column("actor_user_id", sa.Uuid(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("request_id", sa.String(64), nullable=True),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "action IN ('accept_new', 'attach_existing', 'reject', 'defer')",
            name=op.f("ck_discovery_review_decisions_action"),
        ),
        sa.CheckConstraint(
            "idempotency_key ~ '^[A-Za-z0-9._:-]{8,100}$'",
            name=op.f("ck_discovery_review_decisions_idempotency_key_format"),
        ),
        sa.CheckConstraint(
            "payload_digest ~ '^[0-9a-f]{64}$'", name=op.f("ck_discovery_review_decisions_payload_digest_format")
        ),
        sa.CheckConstraint(
            "char_length(reason) BETWEEN 3 AND 1000", name=op.f("ck_discovery_review_decisions_reason_length")
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "run_id"],
            ["discovery_runs.organization_id", "discovery_runs.id"],
            name="fk_drd_org_run",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "candidate_id"],
            ["discovery_candidates.organization_id", "discovery_candidates.id"],
            name="fk_drd_org_candidate",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "account_id"], ["accounts.organization_id", "accounts.id"], name="fk_drd_org_account"
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "actor_user_id"], ["users.organization_id", "users.id"], name="fk_drd_org_actor"
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("fk_discovery_review_decisions_organization_id_organizations"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_discovery_review_decisions")),
        sa.UniqueConstraint(
            "organization_id",
            "idempotency_key",
            name=op.f("uq_discovery_review_decisions_organization_id_idempotency_key"),
        ),
    )
    op.create_index(
        "ix_drd_org_run_candidate",
        "discovery_review_decisions",
        ["organization_id", "run_id", "candidate_id", "recorded_at"],
    )
    op.execute(
        "CREATE TRIGGER discovery_review_decisions_append_only BEFORE UPDATE OR DELETE ON discovery_review_decisions"
        " FOR EACH ROW EXECUTE FUNCTION hermecious_append_only()"
    )


def downgrade() -> None:
    # Runs, review state and decisions are history: on data-bearing databases export first, prefer forward repair.
    op.execute("DROP TRIGGER discovery_review_decisions_append_only ON discovery_review_decisions")
    op.drop_index("ix_drd_org_run_candidate", table_name="discovery_review_decisions")
    op.drop_table("discovery_review_decisions")
    op.drop_table("discovery_run_candidates")
    op.drop_index("ix_discovery_runs_org_created", table_name="discovery_runs")
    op.drop_table("discovery_runs")
