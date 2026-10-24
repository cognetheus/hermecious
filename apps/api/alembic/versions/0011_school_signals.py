"""School operations snapshots: school_signal_snapshots (P3.2).

Revision ID: 0011
Revises: 0010
Create Date: 2026-10-24
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "school_signal_snapshots",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("account_id", sa.Uuid(), nullable=False),
        sa.Column("rubric_version", sa.String(40), nullable=False),
        sa.Column("input_digest", sa.String(64), nullable=False),
        sa.Column("inputs_json", postgresql.JSONB(), nullable=False),
        sa.Column("signals_json", postgresql.JSONB(), nullable=False),
        sa.Column("linked_listings", sa.Integer(), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "input_digest ~ '^[0-9a-f]{64}$'", name=op.f("ck_school_signal_snapshots_input_digest_format")
        ),
        sa.CheckConstraint(
            "linked_listings >= 0", name=op.f("ck_school_signal_snapshots_linked_listings_non_negative")
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "account_id"], ["accounts.organization_id", "accounts.id"],
            name="fk_signal_snapshots_org_account",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "created_by"], ["users.organization_id", "users.id"],
            name="fk_signal_snapshots_org_creator",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"], ["organizations.id"],
            name=op.f("fk_school_signal_snapshots_organization_id_organizations"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_school_signal_snapshots")),
        sa.UniqueConstraint("organization_id", "id", name=op.f("uq_school_signal_snapshots_organization_id_id")),
        sa.UniqueConstraint(
            "organization_id", "account_id", "rubric_version", "input_digest", name="uq_signal_snapshots_input"
        ),
    )  # fmt: skip
    op.create_index(
        "ix_signal_snapshots_org_account_created",
        "school_signal_snapshots",
        ["organization_id", "account_id", "created_at"],
    )
    op.execute(
        "CREATE TRIGGER school_signal_snapshots_append_only BEFORE UPDATE OR DELETE ON school_signal_snapshots"
        " FOR EACH ROW EXECUTE FUNCTION hermecious_append_only()"
    )


def downgrade() -> None:
    # Snapshots are review history: export first on data-bearing databases; prefer forward repair.
    op.execute("DROP TRIGGER school_signal_snapshots_append_only ON school_signal_snapshots")
    op.drop_index("ix_signal_snapshots_org_account_created", table_name="school_signal_snapshots")
    op.drop_table("school_signal_snapshots")
