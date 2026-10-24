"""Identity substrate (ADR-010): organizations, users and server-side sessions."""

import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.persistence.base import Base


class Role(StrEnum):
    OWNER = "owner"
    OPERATOR = "operator"
    OBSERVER = "observer"


class OrganizationStatus(StrEnum):
    ACTIVE = "active"
    SUSPENDED = "suspended"


class Organization(Base):
    __tablename__ = "organizations"
    __table_args__ = (CheckConstraint("status IN ('active', 'suspended')", name="status"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(200))
    timezone: Mapped[str] = mapped_column(String(64), server_default="Asia/Karachi")
    status: Mapped[str] = mapped_column(String(16))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        UniqueConstraint("organization_id", "email_canonical"),
        # Composite FK target so later tables can reference a user *within* an organization (P1.3).
        UniqueConstraint("organization_id", "id"),
        CheckConstraint("role IN ('owner', 'operator', 'observer')", name="role"),
        CheckConstraint("email_canonical = lower(email_canonical)", name="email_canonical_lowercase"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"))
    email_canonical: Mapped[str] = mapped_column(String(320))
    display_name: Mapped[str | None] = mapped_column(String(160))
    password_hash: Mapped[str] = mapped_column(Text)
    role: Mapped[str] = mapped_column(String(16))
    active: Mapped[bool] = mapped_column(Boolean, server_default="true")
    credentials_changed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class AuthSession(Base):
    __tablename__ = "auth_sessions"
    __table_args__ = (
        Index("ix_auth_sessions_user_id", "user_id"),
        Index("ix_auth_sessions_absolute_expires_at", "absolute_expires_at"),
        CheckConstraint("verifier_hash ~ '^[0-9a-f]{64}$'", name="verifier_hash_format"),
        CheckConstraint("idle_expires_at <= absolute_expires_at", name="idle_within_absolute"),
        CheckConstraint("absolute_expires_at > issued_at", name="expires_after_issue"),
    )

    # Lookup key only; possession of the verifier is what proves the session.
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    verifier_hash: Mapped[str] = mapped_column(String(64))
    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    idle_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    absolute_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_request_id: Mapped[str | None] = mapped_column(String(64))
