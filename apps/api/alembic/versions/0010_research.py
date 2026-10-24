"""Source-backed research: research_runs, research_observations, research_claims (P3.1).

Revision ID: 0010
Revises: 0009
Create Date: 2026-10-24
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TERMINAL = "'completed', 'partial', 'failed', 'cancelled'"


def upgrade() -> None:
    op.create_table(
        "research_runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("account_id", sa.Uuid(), nullable=False),
        sa.Column("requested_by", sa.Uuid(), nullable=False),
        sa.Column("source_record_ids", postgresql.JSONB(), nullable=False),
        sa.Column("extractor_version", sa.String(40), nullable=False),
        sa.Column("budget_json", postgresql.JSONB(), nullable=False),
        sa.Column("usage_json", postgresql.JSONB(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("sources_processed", sa.Integer(), nullable=False),
        sa.Column("sources_failed", sa.Integer(), nullable=False),
        sa.Column("claims_proposed", sa.Integer(), nullable=False),
        sa.Column("claims_abstained", sa.Integer(), nullable=False),
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
            f"status IN ('pending', 'running', {TERMINAL})", name=op.f("ck_research_runs_status")
        ),
        sa.CheckConstraint(
            "idempotency_key ~ '^[A-Za-z0-9._:-]{8,100}$'", name=op.f("ck_research_runs_idempotency_key_format")
        ),
        sa.CheckConstraint("request_digest ~ '^[0-9a-f]{64}$'", name=op.f("ck_research_runs_request_digest_format")),
        sa.CheckConstraint(
            "jsonb_array_length(source_record_ids) BETWEEN 1 AND 5", name=op.f("ck_research_runs_source_count")
        ),
        sa.CheckConstraint("claims_proposed BETWEEN 0 AND 25", name=op.f("ck_research_runs_claims_bound")),
        sa.CheckConstraint(
            f"status NOT IN ({TERMINAL}) OR finished_at IS NOT NULL", name=op.f("ck_research_runs_terminal_has_finish")
        ),
        sa.CheckConstraint("version >= 1", name=op.f("ck_research_runs_version_positive")),
        sa.ForeignKeyConstraint(
            ["organization_id", "account_id"], ["accounts.organization_id", "accounts.id"],
            name="fk_research_runs_org_account",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "requested_by"], ["users.organization_id", "users.id"],
            name="fk_research_runs_org_requester",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "job_id"], ["jobs.organization_id", "jobs.id"], name="fk_research_runs_org_job"
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"], ["organizations.id"], name=op.f("fk_research_runs_organization_id_organizations")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_research_runs")),
        sa.UniqueConstraint("organization_id", "id", name=op.f("uq_research_runs_organization_id_id")),
        sa.UniqueConstraint(
            "organization_id", "idempotency_key", name=op.f("uq_research_runs_organization_id_idempotency_key")
        ),
    )  # fmt: skip
    op.create_index(
        "ix_research_runs_org_account_created", "research_runs", ["organization_id", "account_id", "created_at"]
    )

    op.create_table(
        "research_observations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("source_record_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("reason_code", sa.String(80), nullable=True),
        sa.Column("storage_class", sa.String(16), nullable=False),
        sa.Column("rights_policy_version", sa.String(80), nullable=False),
        sa.Column("content_sha256", sa.String(64), nullable=True),
        sa.Column("normalized_chars", sa.Integer(), nullable=False),
        sa.Column("truncated", sa.Boolean(), nullable=False),
        sa.Column("language", sa.String(8), nullable=True),
        sa.Column("retrieved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('processed', 'skipped', 'failed')", name=op.f("ck_research_observations_status")
        ),
        sa.CheckConstraint(
            "content_sha256 IS NULL OR content_sha256 ~ '^[0-9a-f]{64}$'",
            name=op.f("ck_research_observations_content_sha256_format"),
        ),
        sa.CheckConstraint(
            "normalized_chars BETWEEN 0 AND 60000", name=op.f("ck_research_observations_normalized_chars_bound")
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "run_id"], ["research_runs.organization_id", "research_runs.id"],
            name="fk_research_obs_org_run",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "source_record_id"], ["source_records.organization_id", "source_records.id"],
            name="fk_research_obs_org_source",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"], ["organizations.id"],
            name=op.f("fk_research_observations_organization_id_organizations"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_research_observations")),
        sa.UniqueConstraint("organization_id", "id", name=op.f("uq_research_observations_organization_id_id")),
        sa.UniqueConstraint("organization_id", "run_id", "source_record_id", name="uq_research_obs_run_source"),
    )  # fmt: skip

    op.create_table(
        "research_claims",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("account_id", sa.Uuid(), nullable=False),
        sa.Column("observation_id", sa.Uuid(), nullable=False),
        sa.Column("source_record_id", sa.Uuid(), nullable=False),
        sa.Column("claim_type", sa.String(100), nullable=False),
        sa.Column("typed_value_json", postgresql.JSONB(), nullable=False),
        sa.Column("rule_id", sa.String(60), nullable=False),
        sa.Column("extractor_version", sa.String(40), nullable=False),
        sa.Column("storage_class", sa.String(16), nullable=False),
        sa.Column("language", sa.String(8), nullable=False),
        sa.Column("locator_start", sa.Integer(), nullable=False),
        sa.Column("locator_end", sa.Integer(), nullable=False),
        sa.Column("span_sha256", sa.String(64), nullable=False),
        sa.Column("excerpt", sa.Text(), nullable=True),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("fact_id", sa.Uuid(), nullable=True),
        sa.Column("review_key", sa.String(100), nullable=True),
        sa.Column("review_reason", sa.Text(), nullable=True),
        sa.Column("reviewed_by", sa.Uuid(), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('proposed', 'accepted', 'rejected')", name=op.f("ck_research_claims_status")
        ),
        sa.CheckConstraint(
            "locator_start >= 0 AND locator_end > locator_start AND locator_end - locator_start <= 1000",
            name=op.f("ck_research_claims_locator_bounds"),
        ),
        sa.CheckConstraint(
            "excerpt IS NULL OR char_length(excerpt) <= 1000", name=op.f("ck_research_claims_excerpt_length")
        ),
        sa.CheckConstraint(
            "excerpt IS NULL OR storage_class = 'full_allowed'",
            name=op.f("ck_research_claims_excerpt_requires_full_rights"),
        ),
        sa.CheckConstraint("span_sha256 ~ '^[0-9a-f]{64}$'", name=op.f("ck_research_claims_span_sha256_format")),
        sa.CheckConstraint(
            "status <> 'accepted' OR fact_id IS NOT NULL", name=op.f("ck_research_claims_accepted_has_fact")
        ),
        sa.CheckConstraint("version >= 1", name=op.f("ck_research_claims_version_positive")),
        sa.ForeignKeyConstraint(
            ["organization_id", "run_id"], ["research_runs.organization_id", "research_runs.id"],
            name="fk_research_claims_org_run",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "account_id"], ["accounts.organization_id", "accounts.id"],
            name="fk_research_claims_org_account",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "observation_id"],
            ["research_observations.organization_id", "research_observations.id"],
            name="fk_research_claims_org_obs",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "source_record_id"], ["source_records.organization_id", "source_records.id"],
            name="fk_research_claims_org_source",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "fact_id"], ["account_facts.organization_id", "account_facts.id"],
            name="fk_research_claims_org_fact",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "reviewed_by"], ["users.organization_id", "users.id"],
            name="fk_research_claims_org_reviewer",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"], ["organizations.id"], name=op.f("fk_research_claims_organization_id_organizations")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_research_claims")),
        sa.UniqueConstraint("organization_id", "id", name=op.f("uq_research_claims_organization_id_id")),
        sa.UniqueConstraint(
            "organization_id", "observation_id", "claim_type", "locator_start", "locator_end",
            name="uq_research_claims_span",
        ),
        sa.UniqueConstraint(
            "organization_id", "review_key", name=op.f("uq_research_claims_organization_id_review_key")
        ),
    )  # fmt: skip
    op.create_index(
        "ix_research_claims_org_account_status", "research_claims", ["organization_id", "account_id", "status"]
    )


def downgrade() -> None:
    # Research runs, observations and reviewed claims are evidence history: export first, prefer forward repair.
    op.drop_index("ix_research_claims_org_account_status", table_name="research_claims")
    op.drop_table("research_claims")
    op.drop_table("research_observations")
    op.drop_index("ix_research_runs_org_account_created", table_name="research_runs")
    op.drop_table("research_runs")
