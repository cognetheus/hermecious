"""Account management (P1.4): fact corrections, action audits, list/search indexes.

- account_facts: UNIQUE(organization_id, id); nullable supersedes_fact_id (scoped
  self-FK, at most one successor per fact), correction_reason, recorded_by
  (scoped user FK). Facts become append-only (trigger): a correction is a new
  row linked to the prior one, never an overwrite.
- action_audits: append-only, organization-scoped audit trail.
- accounts: keyset index (organization_id, updated_at, id) and a
  text_pattern_ops index for bounded name-prefix search.

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-24
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APPEND_ONLY_FUNCTION = """
CREATE FUNCTION hermecious_append_only() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION '% is append-only', TG_TABLE_NAME USING ERRCODE = 'check_violation';
END;
$$;
"""


def upgrade() -> None:
    op.create_unique_constraint(op.f("uq_account_facts_organization_id_id"), "account_facts", ["organization_id", "id"])
    op.add_column("account_facts", sa.Column("supersedes_fact_id", sa.Uuid(), nullable=True))
    op.add_column("account_facts", sa.Column("correction_reason", sa.Text(), nullable=True))
    op.add_column("account_facts", sa.Column("recorded_by", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        "fk_account_facts_org_supersedes",
        "account_facts",
        "account_facts",
        ["organization_id", "supersedes_fact_id"],
        ["organization_id", "id"],
    )
    op.create_foreign_key(
        "fk_account_facts_org_recorder",
        "account_facts",
        "users",
        ["organization_id", "recorded_by"],
        ["organization_id", "id"],
    )
    op.create_check_constraint(
        op.f("ck_account_facts_correction_has_reason"),
        "account_facts",
        "(supersedes_fact_id IS NULL) = (correction_reason IS NULL)",
    )
    op.create_check_constraint(
        op.f("ck_account_facts_not_self_correcting"),
        "account_facts",
        "supersedes_fact_id IS NULL OR supersedes_fact_id <> id",
    )
    op.create_check_constraint(
        op.f("ck_account_facts_reason_length"),
        "account_facts",
        "correction_reason IS NULL OR char_length(correction_reason) BETWEEN 3 AND 1000",
    )
    op.create_index(
        "uq_account_facts_org_supersedes",
        "account_facts",
        ["organization_id", "supersedes_fact_id"],
        unique=True,
        postgresql_where=sa.text("supersedes_fact_id IS NOT NULL"),
    )

    op.create_table(
        "action_audits",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("actor_user_id", sa.Uuid(), nullable=False),
        sa.Column("action_type", sa.String(80), nullable=False),
        sa.Column("target_type", sa.String(40), nullable=False),
        sa.Column("target_id", sa.Uuid(), nullable=False),
        sa.Column("details_json", postgresql.JSONB(), nullable=False),
        sa.Column("request_id", sa.String(64), nullable=True),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("action_type ~ '^[a-z][a-z0-9_.]{2,79}$'", name=op.f("ck_action_audits_action_type_format")),
        sa.CheckConstraint("target_type ~ '^[a-z][a-z0-9_]{2,39}$'", name=op.f("ck_action_audits_target_type_format")),
        sa.ForeignKeyConstraint(
            ["organization_id", "actor_user_id"],
            ["users.organization_id", "users.id"],
            name="fk_action_audits_org_actor",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"], ["organizations.id"], name=op.f("fk_action_audits_organization_id_organizations")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_action_audits")),
    )
    op.create_index(
        "ix_action_audits_org_target", "action_audits", ["organization_id", "target_type", "target_id", "recorded_at"]
    )

    op.create_index(
        "ix_accounts_org_name_prefix",
        "accounts",
        ["organization_id", "normalized_name"],
        postgresql_ops={"normalized_name": "text_pattern_ops"},
    )
    op.create_index("ix_accounts_org_updated_id", "accounts", ["organization_id", "updated_at", "id"])

    op.execute(APPEND_ONLY_FUNCTION)
    for table in ("account_facts", "action_audits"):
        op.execute(
            f"CREATE TRIGGER {table}_append_only BEFORE UPDATE OR DELETE ON {table}"
            " FOR EACH ROW EXECUTE FUNCTION hermecious_append_only()"
        )


def downgrade() -> None:
    # Corrections and audits are history: on data-bearing databases back up first and
    # prefer a forward repair. Downgrading drops correction linkage and the audit trail.
    for table in ("action_audits", "account_facts"):
        op.execute(f"DROP TRIGGER {table}_append_only ON {table}")
    op.execute("DROP FUNCTION hermecious_append_only()")
    op.drop_index("ix_accounts_org_updated_id", table_name="accounts")
    op.drop_index("ix_accounts_org_name_prefix", table_name="accounts")
    op.drop_index("ix_action_audits_org_target", table_name="action_audits")
    op.drop_table("action_audits")
    op.drop_index("uq_account_facts_org_supersedes", table_name="account_facts")
    op.drop_constraint(op.f("ck_account_facts_reason_length"), "account_facts", type_="check")
    op.drop_constraint(op.f("ck_account_facts_not_self_correcting"), "account_facts", type_="check")
    op.drop_constraint(op.f("ck_account_facts_correction_has_reason"), "account_facts", type_="check")
    op.drop_constraint("fk_account_facts_org_recorder", "account_facts", type_="foreignkey")
    op.drop_constraint("fk_account_facts_org_supersedes", "account_facts", type_="foreignkey")
    op.drop_column("account_facts", "recorded_by")
    op.drop_column("account_facts", "correction_reason")
    op.drop_column("account_facts", "supersedes_fact_id")
    op.drop_constraint(op.f("uq_account_facts_organization_id_id"), "account_facts", type_="unique")
