"""Immutable school operations snapshots (P3.2, ADR-017). Append-only; one per distinct evidence input."""

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
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.persistence.base import Base


class SchoolSignalSnapshot(Base):
    __tablename__ = "school_signal_snapshots"
    __table_args__ = (
        UniqueConstraint("organization_id", "id"),

        ForeignKeyConstraint(
            ["organization_id", "account_id"], ["accounts.organization_id", "accounts.id"],
            name="fk_signal_snapshots_org_account",
        ),
        ForeignKeyConstraint(
            ["organization_id", "created_by"], ["users.organization_id", "users.id"],
            name="fk_signal_snapshots_org_creator",
        ),
        CheckConstraint("input_digest ~ '^[0-9a-f]{64}$'", name="input_digest_format"),
        CheckConstraint("linked_listings >= 0", name="linked_listings_non_negative"),
        Index("ix_signal_snapshots_org_account_created", "organization_id", "account_id", "created_at"),
    )  # fmt: skip

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"))
    account_id: Mapped[uuid.UUID]
    rubric_version: Mapped[str] = mapped_column(String(40))
    input_digest: Mapped[str] = mapped_column(String(64))
    inputs_json: Mapped[list[dict[str, Any]]] = mapped_column(JSONB)
    signals_json: Mapped[dict[str, Any]] = mapped_column(JSONB)
    linked_listings: Mapped[int] = mapped_column(Integer)
    created_by: Mapped[uuid.UUID]
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
