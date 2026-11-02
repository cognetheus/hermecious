"""Intent observations and separate human reviews (P6.1). Both append-only.

Revision ID: 0025
Revises: 0024
Create Date: 2026-11-02
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0025"
down_revision: str | None = "0024"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

PRIMARY = (
    "'interested', 'needs_details', 'objection', 'request_demo', 'defer', 'not_interested', 'opt_out',"
    " 'human_request', 'ambiguous', 'abusive'"
)
APPEND_ONLY = ("intent_observations", "intent_reviews")


def upgrade() -> None:
    op.create_table(
        "intent_observations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("inbound_message_id", sa.Uuid(), nullable=False),
        sa.Column("schema_version", sa.String(16), nullable=False),
        sa.Column("classifier_version", sa.String(40), nullable=False),
        sa.Column("source_revision", sa.String(64), nullable=False),
        sa.Column("primary_intent", sa.String(24), nullable=False),
        sa.Column("requires_human_review", sa.Boolean(), nullable=False),
        sa.Column("result_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(f"primary_intent IN ({PRIMARY})", name=op.f("ck_intent_observations_primary_intent")),
        sa.CheckConstraint("schema_version = 'intent.v1'", name=op.f("ck_intent_observations_schema_version")),
        sa.CheckConstraint(
            "source_revision ~ '^[0-9a-f]{64}$'", name=op.f("ck_intent_observations_source_revision_format")
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "inbound_message_id"],
            ["provider_inbound_messages.organization_id", "provider_inbound_messages.id"],
            name="fk_intent_observations_org_message",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"], ["organizations.id"], name=op.f("fk_intent_observations_organization_id_organizations")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_intent_observations")),
        sa.UniqueConstraint("organization_id", "id", name=op.f("uq_intent_observations_organization_id_id")),
        sa.UniqueConstraint(
            "organization_id",
            "inbound_message_id",
            "classifier_version",
            "source_revision",
            name="uq_intent_observations_version",
        ),  # fmt: skip
    )
    op.create_index("ix_intent_observations_message", "intent_observations", ["inbound_message_id", "created_at"])
    op.create_table(
        "intent_reviews",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("observation_id", sa.Uuid(), nullable=False),
        sa.Column("decision", sa.String(16), nullable=False),
        sa.Column("corrected_primary", sa.String(24), nullable=True),
        sa.Column("note", sa.Text(), nullable=False),
        sa.Column("reviewer_id", sa.Uuid(), nullable=False),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("decision IN ('confirmed', 'corrected')", name=op.f("ck_intent_reviews_decision")),
        sa.CheckConstraint(
            f"(decision = 'corrected') = (corrected_primary IS NOT NULL) AND (corrected_primary IS NULL OR "
            f"corrected_primary IN ({PRIMARY}))",
            name=op.f("ck_intent_reviews_correction_label"),
        ),
        sa.CheckConstraint("char_length(note) <= 500", name=op.f("ck_intent_reviews_note_length")),
        sa.ForeignKeyConstraint(
            ["organization_id", "observation_id"],
            ["intent_observations.organization_id", "intent_observations.id"],
            name="fk_intent_reviews_org_observation",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"], ["organizations.id"], name=op.f("fk_intent_reviews_organization_id_organizations")
        ),
        sa.ForeignKeyConstraint(["reviewer_id"], ["users.id"], name=op.f("fk_intent_reviews_reviewer_id_users")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_intent_reviews")),
        sa.UniqueConstraint("organization_id", "id", name=op.f("uq_intent_reviews_organization_id_id")),
    )
    op.create_index("ix_intent_reviews_observation", "intent_reviews", ["observation_id", "reviewed_at"])
    for table in APPEND_ONLY:
        op.execute(
            f"CREATE TRIGGER {table}_append_only BEFORE UPDATE OR DELETE ON {table}"
            " FOR EACH ROW EXECUTE FUNCTION hermecious_append_only()"
        )


def downgrade() -> None:
    # Observations and reviews are derived from signed messages and human judgement: export first if needed.
    for table in APPEND_ONLY:
        op.execute(f"DROP TRIGGER {table}_append_only ON {table}")
    op.drop_index("ix_intent_reviews_observation", table_name="intent_reviews")
    op.drop_table("intent_reviews")
    op.drop_index("ix_intent_observations_message", table_name="intent_observations")
    op.drop_table("intent_observations")
