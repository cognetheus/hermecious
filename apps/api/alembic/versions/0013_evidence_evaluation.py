"""Evidence quality evaluation: evidence_eval_runs, _items, _verdicts, _remediations (P3.4).

Revision ID: 0013
Revises: 0012
Create Date: 2026-10-24
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0013"
down_revision: str | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

VERDICTS = "'supported', 'unsupported', 'contradicted', 'stale', 'unverifiable'"


def _org_fk(table: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        ["organization_id"], ["organizations.id"], name=op.f(f"fk_{table}_organization_id_organizations")
    )


def upgrade() -> None:
    op.create_table(
        "evidence_eval_runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(24), nullable=False),
        sa.Column("baseline_run_id", sa.Uuid(), nullable=True),
        sa.Column("idempotency_key", sa.String(100), nullable=False),
        sa.Column("selection_method", sa.String(80), nullable=False),
        sa.Column("seed", sa.String(64), nullable=False),
        sa.Column("account_ids", postgresql.JSONB(), nullable=False),
        sa.Column("excluded_accounts", postgresql.JSONB(), nullable=False),
        sa.Column("corpus_fingerprint", sa.String(64), nullable=False),
        sa.Column("corpus_status", sa.String(24), nullable=False),
        sa.Column("real_accounts", sa.Integer(), nullable=False),
        sa.Column("synthetic_accounts", sa.Integer(), nullable=False),
        sa.Column("numerator", sa.Integer(), nullable=True),
        sa.Column("denominator", sa.Integer(), nullable=True),
        sa.Column("still_displayed_failures", sa.Integer(), nullable=True),
        sa.Column("result", sa.String(16), nullable=True),
        sa.Column("result_reason", sa.Text(), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finalized_by", sa.Uuid(), nullable=True),
        sa.Column("finalized_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("kind IN ('baseline', 'post_remediation')", name=op.f("ck_evidence_eval_runs_kind")),
        sa.CheckConstraint(
            "(kind = 'post_remediation') = (baseline_run_id IS NOT NULL)",
            name=op.f("ck_evidence_eval_runs_baseline_link"),
        ),
        sa.CheckConstraint(
            "corpus_status IN ('OK', 'INSUFFICIENT_CORPUS', 'SYNTHETIC_CORPUS')",
            name=op.f("ck_evidence_eval_runs_corpus_status"),
        ),
        sa.CheckConstraint(
            "result IS NULL OR result IN ('PASSED', 'FAILED', 'BLOCKED', 'INCOMPLETE')",
            name=op.f("ck_evidence_eval_runs_result"),
        ),
        sa.CheckConstraint("jsonb_array_length(account_ids) <= 30", name=op.f("ck_evidence_eval_runs_account_bound")),
        sa.CheckConstraint(
            "corpus_fingerprint ~ '^[0-9a-f]{64}$'", name=op.f("ck_evidence_eval_runs_fingerprint_format")
        ),
        sa.CheckConstraint("version >= 1", name=op.f("ck_evidence_eval_runs_version_positive")),
        sa.ForeignKeyConstraint(
            ["organization_id", "baseline_run_id"],
            ["evidence_eval_runs.organization_id", "evidence_eval_runs.id"],
            name="fk_eval_runs_org_baseline",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "created_by"], ["users.organization_id", "users.id"], name="fk_eval_runs_org_creator"
        ),
        _org_fk("evidence_eval_runs"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_evidence_eval_runs")),
        sa.UniqueConstraint("organization_id", "id", name=op.f("uq_evidence_eval_runs_organization_id_id")),
        sa.UniqueConstraint("organization_id", "idempotency_key", name="uq_eval_runs_idempotency"),
    )
    op.create_table(
        "evidence_eval_items",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("account_id", sa.Uuid(), nullable=False),
        sa.Column("item_kind", sa.String(16), nullable=False),
        sa.Column("ref", sa.String(200), nullable=False),
        sa.Column("display_text", sa.Text(), nullable=False),
        sa.Column("fact_ids", postgresql.JSONB(), nullable=False),
        sa.Column("citations", postgresql.JSONB(), nullable=False),
        sa.Column("real_provenance", sa.Boolean(), nullable=False),
        sa.Column("eligibility_at_freeze", sa.String(24), nullable=False),
        sa.Column("verdict", sa.String(16), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.CheckConstraint(
            "item_kind IN ('fact', 'signal', 'dimension')", name=op.f("ck_evidence_eval_items_item_kind")
        ),
        sa.CheckConstraint(f"verdict IS NULL OR verdict IN ({VERDICTS})", name=op.f("ck_evidence_eval_items_verdict")),
        sa.CheckConstraint("version >= 1", name=op.f("ck_evidence_eval_items_version_positive")),
        sa.ForeignKeyConstraint(
            ["organization_id", "run_id"],
            ["evidence_eval_runs.organization_id", "evidence_eval_runs.id"],
            name="fk_eval_items_org_run",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "account_id"],
            ["accounts.organization_id", "accounts.id"],
            name="fk_eval_items_org_account",
        ),
        _org_fk("evidence_eval_items"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_evidence_eval_items")),
        sa.UniqueConstraint("organization_id", "id", name=op.f("uq_evidence_eval_items_organization_id_id")),
        sa.UniqueConstraint("organization_id", "run_id", "item_kind", "ref", name="uq_eval_items_ref"),
    )
    op.create_table(
        "evidence_eval_verdicts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("item_id", sa.Uuid(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("verdict", sa.String(16), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("reviewer_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(f"verdict IN ({VERDICTS})", name=op.f("ck_evidence_eval_verdicts_verdict")),
        sa.CheckConstraint(
            "char_length(reason) BETWEEN 3 AND 1000", name=op.f("ck_evidence_eval_verdicts_reason_length")
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "item_id"],
            ["evidence_eval_items.organization_id", "evidence_eval_items.id"],
            name="fk_eval_verdicts_org_item",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "reviewer_id"],
            ["users.organization_id", "users.id"],
            name="fk_eval_verdicts_org_reviewer",
        ),
        _org_fk("evidence_eval_verdicts"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_evidence_eval_verdicts")),
        sa.UniqueConstraint("organization_id", "item_id", "revision", name="uq_eval_verdicts_revision"),
    )
    op.create_table(
        "evidence_eval_remediations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("item_id", sa.Uuid(), nullable=False),
        sa.Column("correction_fact_id", sa.Uuid(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["organization_id", "item_id"],
            ["evidence_eval_items.organization_id", "evidence_eval_items.id"],
            name="fk_eval_remediations_org_item",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "correction_fact_id"],
            ["account_facts.organization_id", "account_facts.id"],
            name="fk_eval_remediations_org_fact",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "created_by"],
            ["users.organization_id", "users.id"],
            name="fk_eval_remediations_org_creator",
        ),
        _org_fk("evidence_eval_remediations"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_evidence_eval_remediations")),
        sa.UniqueConstraint("organization_id", "item_id", name="uq_eval_remediations_item"),
    )
    for table in ("evidence_eval_verdicts", "evidence_eval_remediations"):
        op.execute(
            f"CREATE TRIGGER {table}_append_only BEFORE UPDATE OR DELETE ON {table}"
            " FOR EACH ROW EXECUTE FUNCTION hermecious_append_only()"
        )


def downgrade() -> None:
    # Evaluation runs and verdicts are audit evidence: export first on data-bearing databases.
    for table in ("evidence_eval_remediations", "evidence_eval_verdicts"):
        op.execute(f"DROP TRIGGER {table}_append_only ON {table}")
    for table in ("evidence_eval_remediations", "evidence_eval_verdicts", "evidence_eval_items", "evidence_eval_runs"):
        op.drop_table(table)
