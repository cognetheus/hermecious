"""Grounded reply proposals and their reviews (P6.2). Both append-only.

Revision ID: 0027
Revises: 0026
Create Date: 2026-11-09
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0027"
down_revision: str | None = "0026"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APPEND_ONLY = ("reply_proposals", "reply_proposal_reviews")


def _fk(cols: list[str], target: str, name: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(["organization_id", *cols], [f"{target}.organization_id", f"{target}.id"], name=name)


def upgrade() -> None:
    op.create_table(
        "reply_proposals",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("inbound_message_id", sa.Uuid(), nullable=False),
        sa.Column("thread_id", sa.Uuid(), nullable=False),
        sa.Column("intent_observation_id", sa.Uuid(), nullable=True),
        sa.Column("offer_id", sa.Uuid(), nullable=True),
        sa.Column("offer_revision", sa.Integer(), nullable=True),
        sa.Column("input_digest", sa.String(64), nullable=False),
        sa.Column("lineage_seq", sa.Integer(), nullable=False),
        sa.Column("schema_version", sa.String(16), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("recommended_action", sa.String(40), nullable=False),
        sa.Column("proposal_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("composer_version", sa.String(40), nullable=False),
        sa.Column("policy_version", sa.String(40), nullable=False),
        sa.Column("requested_by", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("status IN ('proposed', 'abstained')", name=op.f("ck_reply_proposals_status")),
        sa.CheckConstraint("schema_version = 'reply.v1'", name=op.f("ck_reply_proposals_schema_version")),
        sa.CheckConstraint("input_digest ~ '^[0-9a-f]{64}$'", name=op.f("ck_reply_proposals_input_digest_format")),
        sa.CheckConstraint("lineage_seq >= 1", name=op.f("ck_reply_proposals_lineage_seq_positive")),
        _fk(["inbound_message_id"], "provider_inbound_messages", "fk_reply_proposals_org_message"),
        _fk(["thread_id"], "inbox_threads", "fk_reply_proposals_org_thread"),
        _fk(["intent_observation_id"], "intent_observations", "fk_reply_proposals_org_observation"),
        _fk(["offer_id"], "offers", "fk_reply_proposals_org_offer"),
        sa.ForeignKeyConstraint(
            ["organization_id"], ["organizations.id"], name=op.f("fk_reply_proposals_organization_id_organizations")
        ),
        sa.ForeignKeyConstraint(["requested_by"], ["users.id"], name=op.f("fk_reply_proposals_requested_by_users")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_reply_proposals")),
        sa.UniqueConstraint("organization_id", "id", name=op.f("uq_reply_proposals_organization_id_id")),
        sa.UniqueConstraint("organization_id", "inbound_message_id", "input_digest", name="uq_reply_proposals_input"),
        sa.UniqueConstraint("inbound_message_id", "lineage_seq", name="uq_reply_proposals_lineage"),
    )
    op.create_index("ix_reply_proposals_message", "reply_proposals", ["inbound_message_id", "lineage_seq"])
    op.create_table(
        "reply_proposal_reviews",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("proposal_id", sa.Uuid(), nullable=False),
        sa.Column("decision", sa.String(16), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("reviewer_id", sa.Uuid(), nullable=False),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("decision = 'rejected'", name=op.f("ck_reply_proposal_reviews_decision")),
        sa.CheckConstraint(
            "char_length(reason) BETWEEN 3 AND 500", name=op.f("ck_reply_proposal_reviews_reason_length")
        ),
        _fk(["proposal_id"], "reply_proposals", "fk_reply_proposal_reviews_org_proposal"),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("fk_reply_proposal_reviews_organization_id_organizations"),
        ),
        sa.ForeignKeyConstraint(
            ["reviewer_id"], ["users.id"], name=op.f("fk_reply_proposal_reviews_reviewer_id_users")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_reply_proposal_reviews")),
        sa.UniqueConstraint("organization_id", "id", name=op.f("uq_reply_proposal_reviews_organization_id_id")),
    )
    op.create_index("ix_reply_proposal_reviews_proposal", "reply_proposal_reviews", ["proposal_id", "reviewed_at"])
    for table in APPEND_ONLY:
        op.execute(
            f"CREATE TRIGGER {table}_append_only BEFORE UPDATE OR DELETE ON {table}"
            " FOR EACH ROW EXECUTE FUNCTION hermecious_append_only()"
        )


def downgrade() -> None:
    # Proposals and reviews are audit evidence: export first on data-bearing databases.
    for table in APPEND_ONLY:
        op.execute(f"DROP TRIGGER {table}_append_only ON {table}")
    op.drop_index("ix_reply_proposal_reviews_proposal", table_name="reply_proposal_reviews")
    op.drop_table("reply_proposal_reviews")
    op.drop_index("ix_reply_proposals_message", table_name="reply_proposals")
    op.drop_table("reply_proposals")
