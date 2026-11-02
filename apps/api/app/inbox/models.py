"""Read-only WhatsApp inbox projection (P5.4, ADR-029).

A thread is one external party on one provider connection, keyed by the sender's keyed digest. It holds only
ordering and review state; messages and statuses stay in the signed P5.2/P5.3 source tables and are read from there.
Both writers (the P5.2 processor and the P5.3 test send) and the rebuild only move values forward (`greatest`), so
redelivery, racing workers and repeated rebuilds converge on the same row.
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.persistence.base import Base


class InboxThread(Base):
    __tablename__ = "inbox_threads"
    __table_args__ = (
        UniqueConstraint("organization_id", "id"),
        UniqueConstraint("provider_connection_id", "party_key_id", "party_digest", name="uq_inbox_threads_party"),
        ForeignKeyConstraint(
            ["organization_id", "provider_connection_id"],
            ["provider_connections.organization_id", "provider_connections.id"],
            name="fk_inbox_threads_org_connection",
        ),
        CheckConstraint("party_digest ~ '^[0-9a-f]{64}$'", name="party_digest_format"),
        CheckConstraint("reviewed_through_seq <= last_inbound_seq", name="reviewed_not_ahead"),
        Index("ix_inbox_threads_activity", "organization_id", "last_activity_at", "id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"))
    provider_connection_id: Mapped[uuid.UUID]
    party_key_id: Mapped[str] = mapped_column(String(16))
    party_digest: Mapped[str] = mapped_column(String(64))
    party_hint: Mapped[str] = mapped_column(String(40))
    last_activity_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_inbound_seq: Mapped[int] = mapped_column(BigInteger)  # P5.2 arrival order of the newest inbound, 0 if none
    reviewed_through_seq: Mapped[int] = mapped_column(BigInteger)
    reviewed_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    version: Mapped[int] = mapped_column(Integer)
