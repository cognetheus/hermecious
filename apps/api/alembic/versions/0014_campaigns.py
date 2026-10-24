"""Campaign planning: campaigns, campaign_accounts, campaign_commands, campaign_daily_usage (P4.1).

Revision ID: 0014
Revises: 0013
Create Date: 2026-10-24
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0014"
down_revision: str | None = "0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _org_fk(table: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        ["organization_id"], ["organizations.id"], name=op.f(f"fk_{table}_organization_id_organizations")
    )


def upgrade() -> None:
    op.create_table(
        "campaigns",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("vertical_slug", sa.String(80), nullable=False),
        sa.Column("city", sa.String(120), nullable=False),
        sa.Column("district", sa.String(160), nullable=True),
        sa.Column("mode", sa.String(16), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("offer_id", sa.Uuid(), nullable=False),
        sa.Column("offer_revision_id", sa.Uuid(), nullable=False),
        sa.Column("capability_version", sa.String(80), nullable=False),
        sa.Column("rules_json", postgresql.JSONB(), nullable=False),
        sa.Column("rules_digest", sa.String(64), nullable=False),
        sa.Column("rules_version", sa.String(40), nullable=False),
        sa.Column("budgets_json", postgresql.JSONB(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("mode IN ('live', 'fixture')", name=op.f("ck_campaigns_mode")),
        sa.CheckConstraint("status IN ('draft', 'active', 'paused', 'cancelled')", name=op.f("ck_campaigns_status")),
        sa.CheckConstraint("vertical_slug = 'schools' AND city = 'Lahore'", name=op.f("ck_campaigns_scope")),
        sa.CheckConstraint("rules_digest ~ '^[0-9a-f]{64}$'", name=op.f("ck_campaigns_rules_digest_format")),
        sa.CheckConstraint("revision >= 1", name=op.f("ck_campaigns_revision_positive")),
        sa.CheckConstraint("char_length(name) BETWEEN 3 AND 120", name=op.f("ck_campaigns_name_length")),
        sa.ForeignKeyConstraint(
            ["organization_id", "offer_id"], ["offers.organization_id", "offers.id"], name="fk_campaigns_org_offer"
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "created_by"], ["users.organization_id", "users.id"], name="fk_campaigns_org_creator"
        ),
        _org_fk("campaigns"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_campaigns")),
        sa.UniqueConstraint("organization_id", "id", name=op.f("uq_campaigns_organization_id_id")),
    )
    op.create_table(
        "campaign_accounts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("campaign_id", sa.Uuid(), nullable=False),
        sa.Column("account_id", sa.Uuid(), nullable=False),
        sa.Column("stage", sa.String(32), nullable=False),
        sa.Column("assessment_id", sa.Uuid(), nullable=True),
        sa.Column("assessment_revision", sa.Integer(), nullable=True),
        sa.Column("offer_revision_id", sa.Uuid(), nullable=False),
        sa.Column("rules_digest", sa.String(64), nullable=False),
        sa.Column("item_digest", sa.String(64), nullable=True),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("decided_by", sa.Uuid(), nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("stage IN ('approved_for_drafting', 'excluded')", name=op.f("ck_campaign_accounts_stage")),
        sa.CheckConstraint("char_length(reason) BETWEEN 3 AND 500", name=op.f("ck_campaign_accounts_reason_length")),
        sa.CheckConstraint("version >= 1", name=op.f("ck_campaign_accounts_version_positive")),
        sa.ForeignKeyConstraint(
            ["organization_id", "campaign_id"],
            ["campaigns.organization_id", "campaigns.id"],
            name="fk_campaign_accounts_org_campaign",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "account_id"],
            ["accounts.organization_id", "accounts.id"],
            name="fk_campaign_accounts_org_account",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "assessment_id"],
            ["assessments.organization_id", "assessments.id"],
            name="fk_campaign_accounts_org_assessment",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "decided_by"],
            ["users.organization_id", "users.id"],
            name="fk_campaign_accounts_org_decider",
        ),
        _org_fk("campaign_accounts"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_campaign_accounts")),
        sa.UniqueConstraint("organization_id", "id", name=op.f("uq_campaign_accounts_organization_id_id")),
        sa.UniqueConstraint("organization_id", "campaign_id", "account_id", name="uq_campaign_accounts_member"),
    )
    op.create_table(
        "campaign_commands",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("campaign_id", sa.Uuid(), nullable=False),
        sa.Column("idempotency_key", sa.String(100), nullable=False),
        sa.Column("request_digest", sa.String(64), nullable=False),
        sa.Column("outcome_json", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "request_digest ~ '^[0-9a-f]{64}$'", name=op.f("ck_campaign_commands_request_digest_format")
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "campaign_id"],
            ["campaigns.organization_id", "campaigns.id"],
            name="fk_campaign_commands_org_campaign",
        ),
        _org_fk("campaign_commands"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_campaign_commands")),
        sa.UniqueConstraint("organization_id", "idempotency_key", name="uq_campaign_commands_key"),
    )
    op.create_table(
        "campaign_daily_usage",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("campaign_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("used", sa.Integer(), nullable=False),
        sa.CheckConstraint("kind IN ('approval', 'draft')", name=op.f("ck_campaign_daily_usage_kind")),
        sa.CheckConstraint("used >= 0", name=op.f("ck_campaign_daily_usage_used_non_negative")),
        sa.ForeignKeyConstraint(
            ["organization_id", "campaign_id"],
            ["campaigns.organization_id", "campaigns.id"],
            name="fk_campaign_usage_org_campaign",
        ),
        _org_fk("campaign_daily_usage"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_campaign_daily_usage")),
        sa.UniqueConstraint("organization_id", "campaign_id", "kind", "day", name="uq_campaign_usage_day"),
    )
    op.execute(
        "CREATE TRIGGER campaign_commands_append_only BEFORE UPDATE OR DELETE ON campaign_commands"
        " FOR EACH ROW EXECUTE FUNCTION hermecious_append_only()"
    )


def downgrade() -> None:
    # Campaign planning history: export first on data-bearing databases.
    op.execute("DROP TRIGGER campaign_commands_append_only ON campaign_commands")
    for table in ("campaign_daily_usage", "campaign_commands", "campaign_accounts", "campaigns"):
        op.drop_table(table)
