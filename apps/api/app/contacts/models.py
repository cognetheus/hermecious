"""Contacts, permission evidence and suppressions (P4.3, ADR-022). Org-scoped; no plaintext addresses.

- `contacts` and `suppression_entries` are append-only. A suppression is never lifted in P4.3.
- `contact_permissions` rows are immutable evidence; only the review state moves, forward only, guarded by a
  trigger: pending -> verified | rejected | revoked | superseded, verified -> revoked | superseded.
"""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.persistence.base import Base

ROLES = ("school_office", "admissions_office", "accounts_office", "principal_office")
PURPOSES = ("marketing", "utility")
CAPTURE_METHODS = ("signed_paper_form", "web_form_checkbox", "whatsapp_opt_in_reply", "recorded_call")
PERMISSION_STATUSES = ("pending", "verified", "rejected", "revoked", "superseded")
SUPPRESSION_REASONS = ("opt_out", "complaint", "owner_request", "wrong_number")


def _in(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{v}'" for v in values)


def _org_fk(cols: list[str], target: str, name: str) -> ForeignKeyConstraint:
    return ForeignKeyConstraint(["organization_id", *cols], [f"{target}.organization_id", f"{target}.id"], name=name)


class Contact(Base):
    __tablename__ = "contacts"
    __table_args__ = (
        UniqueConstraint("organization_id", "id"),
        UniqueConstraint("organization_id", "channel", "key_id", "address_digest", name="uq_contacts_address"),
        _org_fk(["account_id"], "accounts", "fk_contacts_org_account"),
        _org_fk(["created_by"], "users", "fk_contacts_org_creator"),
        CheckConstraint("channel = 'whatsapp'", name="channel"),
        CheckConstraint(f"role IN ({_in(ROLES)})", name="role"),
        CheckConstraint("address_digest ~ '^[0-9a-f]{64}$'", name="digest_format"),
        Index("ix_contacts_org_account", "organization_id", "account_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"))
    account_id: Mapped[uuid.UUID]
    channel: Mapped[str] = mapped_column(String(16))
    role: Mapped[str] = mapped_column(String(32))
    key_id: Mapped[str] = mapped_column(String(16))
    address_digest: Mapped[str] = mapped_column(String(64))
    address_hint: Mapped[str] = mapped_column(String(40))
    created_by: Mapped[uuid.UUID]
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ContactPermission(Base):
    __tablename__ = "contact_permissions"
    __table_args__ = (
        UniqueConstraint("organization_id", "id"),
        _org_fk(["contact_id"], "contacts", "fk_contact_permissions_org_contact"),
        _org_fk(["supersedes_id"], "contact_permissions", "fk_contact_permissions_org_supersedes"),
        _org_fk(["recorded_by"], "users", "fk_contact_permissions_org_recorder"),
        _org_fk(["reviewed_by"], "users", "fk_contact_permissions_org_reviewer"),
        _org_fk(["revoked_by"], "users", "fk_contact_permissions_org_revoker"),
        CheckConstraint("channel = 'whatsapp'", name="channel"),
        CheckConstraint(f"purpose IN ({_in(PURPOSES)})", name="purpose"),
        CheckConstraint("basis = 'explicit_opt_in'", name="basis"),
        CheckConstraint(f"capture_method IN ({_in(CAPTURE_METHODS)})", name="capture_method"),
        CheckConstraint(f"status IN ({_in(PERMISSION_STATUSES)})", name="status"),
        CheckConstraint("proof_digest ~ '^[0-9a-f]{64}$'", name="proof_digest_format"),
        CheckConstraint("expires_at > captured_at", name="expires_after_capture"),
        CheckConstraint(
            "status <> 'verified' OR (reviewed_by IS NOT NULL AND reviewed_at IS NOT NULL"
            " AND effective_at IS NOT NULL AND reviewed_by <> recorded_by)",
            name="verified_by_another_reviewer",
        ),
        CheckConstraint(
            "status <> 'rejected' OR (reviewed_by IS NOT NULL AND review_reason IS NOT NULL)", name="rejection_reason"
        ),
        CheckConstraint(
            "status <> 'revoked' OR (revoked_by IS NOT NULL AND revoked_at IS NOT NULL AND revoke_reason IS NOT NULL)",
            name="revocation_reason",
        ),
        CheckConstraint("version >= 1", name="version_positive"),
        Index(
            "uq_contact_permissions_open",
            "organization_id",
            "contact_id",
            "channel",
            "purpose",
            unique=True,
            postgresql_where=text("status IN ('pending', 'verified')"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"))
    contact_id: Mapped[uuid.UUID]
    channel: Mapped[str] = mapped_column(String(16))
    purpose: Mapped[str] = mapped_column(String(16))
    business_name: Mapped[str] = mapped_column(String(120))
    basis: Mapped[str] = mapped_column(String(32))
    capture_method: Mapped[str] = mapped_column(String(32))
    consent_wording_version: Mapped[str] = mapped_column(String(60))
    proof_kind: Mapped[str] = mapped_column(String(32))
    proof_key_id: Mapped[str] = mapped_column(String(16))
    proof_digest: Mapped[str] = mapped_column(String(64))
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(16))
    recorded_by: Mapped[uuid.UUID]
    reviewed_by: Mapped[uuid.UUID | None]
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    review_reason: Mapped[str | None] = mapped_column(Text)
    effective_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_by: Mapped[uuid.UUID | None]
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoke_reason: Mapped[str | None] = mapped_column(Text)
    supersedes_id: Mapped[uuid.UUID | None]
    version: Mapped[int] = mapped_column(Integer)


class SuppressionEntry(Base):
    __tablename__ = "suppression_entries"
    __table_args__ = (
        UniqueConstraint("organization_id", "id"),
        UniqueConstraint("organization_id", "channel", "key_id", "address_digest", name="uq_suppression_address"),
        _org_fk(["contact_id"], "contacts", "fk_suppression_entries_org_contact"),
        _org_fk(["created_by"], "users", "fk_suppression_entries_org_creator"),
        CheckConstraint("channel = 'whatsapp'", name="channel"),
        CheckConstraint(f"reason IN ({_in(SUPPRESSION_REASONS)})", name="reason"),
        CheckConstraint("address_digest ~ '^[0-9a-f]{64}$'", name="digest_format"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"))
    channel: Mapped[str] = mapped_column(String(16))
    key_id: Mapped[str] = mapped_column(String(16))
    address_digest: Mapped[str] = mapped_column(String(64))
    address_hint: Mapped[str] = mapped_column(String(40))
    reason: Mapped[str] = mapped_column(String(32))
    contact_id: Mapped[uuid.UUID | None]
    created_by: Mapped[uuid.UUID]
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ContactCommand(Base):
    """Idempotency record for contact/permission/suppression commands."""

    __tablename__ = "contact_commands"
    __table_args__ = (
        UniqueConstraint("organization_id", "idempotency_key", name="uq_contact_commands_key"),
        CheckConstraint("request_digest ~ '^[0-9a-f]{64}$'", name="request_digest_format"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"))
    idempotency_key: Mapped[str] = mapped_column(String(100))
    request_digest: Mapped[str] = mapped_column(String(64))
    outcome_json: Mapped[dict[str, Any]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
