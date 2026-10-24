"""Offer catalog: offers and immutable offer_revisions (P1.3).

- `users` gains UNIQUE(organization_id, id) (additive) so revisions can reference
  their creator/approver *within* the organization.
- offers <-> offer_revisions reference each other; the offer -> revision FKs are
  added after both tables exist.
- A trigger makes revision content immutable: only the lifecycle columns
  (state, approved_by, approved_at, published_at) may change, only along
  draft -> published -> retired or draft -> retired, and rows are never deleted.

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-23
"""

from collections.abc import Sequence
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

IMMUTABILITY_FUNCTION = """
CREATE FUNCTION offer_revisions_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'offer revisions are append-only' USING ERRCODE = 'check_violation';
    END IF;
    IF (NEW.id, NEW.organization_id, NEW.offer_id, NEW.revision, NEW.capability_version,
        NEW.approved_claims_json, NEW.capability_matrix_json, NEW.price_rules_json, NEW.exclusions_json,
        NEW.dependencies_json, NEW.evidence_references_json, NEW.created_by, NEW.content_sha256, NEW.created_at)
       IS DISTINCT FROM
       (OLD.id, OLD.organization_id, OLD.offer_id, OLD.revision, OLD.capability_version,
        OLD.approved_claims_json, OLD.capability_matrix_json, OLD.price_rules_json, OLD.exclusions_json,
        OLD.dependencies_json, OLD.evidence_references_json, OLD.created_by, OLD.content_sha256, OLD.created_at)
    THEN
        RAISE EXCEPTION 'offer revision content is immutable' USING ERRCODE = 'check_violation';
    END IF;
    IF OLD.state = 'draft' AND NEW.state IN ('draft', 'published', 'retired') THEN
        IF OLD.state = NEW.state AND (NEW.approved_by, NEW.approved_at, NEW.published_at)
                                     IS DISTINCT FROM (OLD.approved_by, OLD.approved_at, OLD.published_at) THEN
            RAISE EXCEPTION 'approval fields change only on publication' USING ERRCODE = 'check_violation';
        END IF;
        RETURN NEW;
    END IF;
    IF OLD.state = 'published' AND NEW.state IN ('published', 'retired')
       AND (NEW.approved_by, NEW.approved_at, NEW.published_at)
           IS NOT DISTINCT FROM (OLD.approved_by, OLD.approved_at, OLD.published_at) THEN
        RETURN NEW;
    END IF;
    IF OLD.state = 'retired' AND NEW.state = 'retired'
       AND (NEW.approved_by, NEW.approved_at, NEW.published_at)
           IS NOT DISTINCT FROM (OLD.approved_by, OLD.approved_at, OLD.published_at) THEN
        RETURN NEW;
    END IF;
    RAISE EXCEPTION 'invalid offer revision state transition' USING ERRCODE = 'check_violation';
END;
$$;
"""


def _ts(name: str, nullable: bool = False) -> sa.Column[datetime]:
    return sa.Column(name, sa.DateTime(timezone=True), nullable=nullable)


def _json(name: str) -> sa.Column[object]:
    return sa.Column(name, postgresql.JSONB(), nullable=False)


def upgrade() -> None:
    op.create_unique_constraint(op.f("uq_users_organization_id_id"), "users", ["organization_id", "id"])

    op.create_table(
        "offers",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("vertical_id", sa.Uuid(), nullable=False),
        sa.Column("code", sa.String(100), nullable=False),
        sa.Column("audience", sa.String(200), nullable=False),
        sa.Column("current_draft_revision_id", sa.Uuid(), nullable=True),
        sa.Column("published_revision_id", sa.Uuid(), nullable=True),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        _ts("created_at"),
        _ts("updated_at"),
        sa.CheckConstraint("status IN ('draft', 'published', 'archived')", name=op.f("ck_offers_status")),
        sa.CheckConstraint("code ~ '^[a-z][a-z0-9_]{2,99}$'", name=op.f("ck_offers_code_format")),
        sa.CheckConstraint("version >= 1", name=op.f("ck_offers_version_positive")),
        sa.CheckConstraint(
            "status <> 'published' OR published_revision_id IS NOT NULL", name=op.f("ck_offers_published_has_revision")
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"], ["organizations.id"], name=op.f("fk_offers_organization_id_organizations")
        ),
        sa.ForeignKeyConstraint(["vertical_id"], ["verticals.id"], name=op.f("fk_offers_vertical_id_verticals")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_offers")),
        sa.UniqueConstraint("organization_id", "code", name=op.f("uq_offers_organization_id_code")),
        sa.UniqueConstraint("organization_id", "id", name=op.f("uq_offers_organization_id_id")),
    )

    op.create_table(
        "offer_revisions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("offer_id", sa.Uuid(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("state", sa.String(16), nullable=False),
        sa.Column("capability_version", sa.String(80), nullable=False),
        _json("approved_claims_json"),
        _json("capability_matrix_json"),
        _json("price_rules_json"),
        _json("exclusions_json"),
        _json("dependencies_json"),
        _json("evidence_references_json"),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        sa.Column("approved_by", sa.Uuid(), nullable=True),
        _ts("approved_at", nullable=True),
        _ts("published_at", nullable=True),
        sa.Column("content_sha256", sa.String(64), nullable=False),
        _ts("created_at"),
        sa.CheckConstraint("state IN ('draft', 'published', 'retired')", name=op.f("ck_offer_revisions_state")),
        sa.CheckConstraint("revision >= 1", name=op.f("ck_offer_revisions_revision_positive")),
        sa.CheckConstraint("content_sha256 ~ '^[0-9a-f]{64}$'", name=op.f("ck_offer_revisions_content_sha256_format")),
        sa.CheckConstraint(
            "state = 'draft' OR (approved_by IS NOT NULL AND approved_at IS NOT NULL AND published_at IS NOT NULL)"
            " OR (state = 'retired' AND published_at IS NULL)",
            name=op.f("ck_offer_revisions_published_has_approval"),
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "offer_id"],
            ["offers.organization_id", "offers.id"],
            name="fk_offer_revisions_org_offer",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "created_by"],
            ["users.organization_id", "users.id"],
            name="fk_offer_revisions_org_creator",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "approved_by"],
            ["users.organization_id", "users.id"],
            name="fk_offer_revisions_org_approver",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"], ["organizations.id"], name=op.f("fk_offer_revisions_organization_id_organizations")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_offer_revisions")),
        sa.UniqueConstraint(
            "organization_id", "offer_id", "revision", name=op.f("uq_offer_revisions_organization_id_offer_id_revision")
        ),
        sa.UniqueConstraint("organization_id", "id", name=op.f("uq_offer_revisions_organization_id_id")),
    )
    op.create_foreign_key(
        "fk_offers_org_current_draft",
        "offers",
        "offer_revisions",
        ["organization_id", "current_draft_revision_id"],
        ["organization_id", "id"],
    )
    op.create_foreign_key(
        "fk_offers_org_published",
        "offers",
        "offer_revisions",
        ["organization_id", "published_revision_id"],
        ["organization_id", "id"],
    )

    op.execute(IMMUTABILITY_FUNCTION)
    op.execute(
        "CREATE TRIGGER offer_revisions_immutable BEFORE UPDATE OR DELETE ON offer_revisions"
        " FOR EACH ROW EXECUTE FUNCTION offer_revisions_guard()"
    )


def downgrade() -> None:
    # Published revisions are historical approvals: on data-bearing databases back up
    # first and prefer a forward repair (docs/contracts/offer-catalog.md).
    op.execute("DROP TRIGGER offer_revisions_immutable ON offer_revisions")
    op.execute("DROP FUNCTION offer_revisions_guard()")
    op.drop_constraint("fk_offers_org_published", "offers", type_="foreignkey")
    op.drop_constraint("fk_offers_org_current_draft", "offers", type_="foreignkey")
    op.drop_table("offer_revisions")
    op.drop_table("offers")
    op.drop_constraint(op.f("uq_users_organization_id_id"), "users", type_="unique")
