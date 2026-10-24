"""Campaign planning (P4.1, ADR-020). Internal planning only: nothing here authorizes or sends a message."""

import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.persistence.base import Base


class Campaign(Base):
    __tablename__ = "campaigns"
    __table_args__ = (
        UniqueConstraint("organization_id", "id"),
        ForeignKeyConstraint(
            ["organization_id", "offer_id"], ["offers.organization_id", "offers.id"], name="fk_campaigns_org_offer"
        ),
        ForeignKeyConstraint(
            ["organization_id", "created_by"], ["users.organization_id", "users.id"], name="fk_campaigns_org_creator"
        ),
        CheckConstraint("mode IN ('live', 'fixture')", name="mode"),
        CheckConstraint("status IN ('draft', 'active', 'paused', 'cancelled')", name="status"),
        CheckConstraint("vertical_slug = 'schools' AND city = 'Lahore'", name="scope"),
        CheckConstraint("rules_digest ~ '^[0-9a-f]{64}$'", name="rules_digest_format"),
        CheckConstraint("revision >= 1", name="revision_positive"),
        CheckConstraint("char_length(name) BETWEEN 3 AND 120", name="name_length"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"))
    name: Mapped[str] = mapped_column(String(120))
    vertical_slug: Mapped[str] = mapped_column(String(80))
    city: Mapped[str] = mapped_column(String(120))
    district: Mapped[str | None] = mapped_column(String(160))
    mode: Mapped[str] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(16))
    offer_id: Mapped[uuid.UUID]
    offer_revision_id: Mapped[uuid.UUID]
    capability_version: Mapped[str] = mapped_column(String(80))
    rules_json: Mapped[dict[str, Any]] = mapped_column(JSONB)
    rules_digest: Mapped[str] = mapped_column(String(64))
    rules_version: Mapped[str] = mapped_column(String(40))
    budgets_json: Mapped[dict[str, Any]] = mapped_column(JSONB)
    revision: Mapped[int] = mapped_column(Integer)
    created_by: Mapped[uuid.UUID]
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class CampaignAccount(Base):
    """Membership decision for one account: approved for drafting (not contact) or excluded. Exclusion wins."""

    __tablename__ = "campaign_accounts"
    __table_args__ = (
        UniqueConstraint("organization_id", "id"),
        UniqueConstraint("organization_id", "campaign_id", "account_id", name="uq_campaign_accounts_member"),
        ForeignKeyConstraint(
            ["organization_id", "campaign_id"],
            ["campaigns.organization_id", "campaigns.id"],
            name="fk_campaign_accounts_org_campaign",
        ),
        ForeignKeyConstraint(
            ["organization_id", "account_id"],
            ["accounts.organization_id", "accounts.id"],
            name="fk_campaign_accounts_org_account",
        ),
        ForeignKeyConstraint(
            ["organization_id", "assessment_id"],
            ["assessments.organization_id", "assessments.id"],
            name="fk_campaign_accounts_org_assessment",
        ),
        ForeignKeyConstraint(
            ["organization_id", "decided_by"],
            ["users.organization_id", "users.id"],
            name="fk_campaign_accounts_org_decider",
        ),
        CheckConstraint("stage IN ('approved_for_drafting', 'excluded')", name="stage"),
        CheckConstraint("char_length(reason) BETWEEN 3 AND 500", name="reason_length"),
        CheckConstraint("version >= 1", name="version_positive"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"))
    campaign_id: Mapped[uuid.UUID]
    account_id: Mapped[uuid.UUID]
    stage: Mapped[str] = mapped_column(String(32))
    assessment_id: Mapped[uuid.UUID | None]
    assessment_revision: Mapped[int | None] = mapped_column(Integer)
    offer_revision_id: Mapped[uuid.UUID]
    rules_digest: Mapped[str] = mapped_column(String(64))
    item_digest: Mapped[str | None] = mapped_column(String(64))
    reason: Mapped[str] = mapped_column(Text)
    version: Mapped[int] = mapped_column(Integer)
    decided_by: Mapped[uuid.UUID]
    decided_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class CampaignCommand(Base):
    """Idempotency ledger for membership commands: (org, key) -> request digest and outcome."""

    __tablename__ = "campaign_commands"
    __table_args__ = (
        UniqueConstraint("organization_id", "idempotency_key", name="uq_campaign_commands_key"),
        ForeignKeyConstraint(
            ["organization_id", "campaign_id"],
            ["campaigns.organization_id", "campaigns.id"],
            name="fk_campaign_commands_org_campaign",
        ),
        CheckConstraint("request_digest ~ '^[0-9a-f]{64}$'", name="request_digest_format"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"))
    campaign_id: Mapped[uuid.UUID]
    idempotency_key: Mapped[str] = mapped_column(String(100))
    request_digest: Mapped[str] = mapped_column(String(64))
    outcome_json: Mapped[dict[str, Any]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class CampaignDailyUsage(Base):
    """Local (Asia/Karachi) day counters for research approvals and future drafts. Not channel limits."""

    __tablename__ = "campaign_daily_usage"
    __table_args__ = (
        UniqueConstraint("organization_id", "campaign_id", "kind", "day", name="uq_campaign_usage_day"),
        ForeignKeyConstraint(
            ["organization_id", "campaign_id"],
            ["campaigns.organization_id", "campaigns.id"],
            name="fk_campaign_usage_org_campaign",
        ),
        CheckConstraint("kind IN ('approval', 'draft')", name="kind"),
        CheckConstraint("used >= 0", name="used_non_negative"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"))
    campaign_id: Mapped[uuid.UUID]
    kind: Mapped[str] = mapped_column(String(16))
    day: Mapped[date] = mapped_column(Date)
    used: Mapped[int] = mapped_column(Integer)
