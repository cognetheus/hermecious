"""WhatsApp provider records: connections (P5.1, ADR-026) and the signed webhook inbox (P5.2, ADR-027).

A phone-number ID belongs to exactly one organization. The row stores identifiers and the *name* of the secret
source (`credential_ref`); secrets stay in the environment.
"""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Identity,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.persistence.base import Base


class ProviderConnection(Base):
    __tablename__ = "provider_connections"
    __table_args__ = (
        UniqueConstraint("organization_id", "id"),
        UniqueConstraint("provider", "phone_number_id", name="uq_provider_connections_phone"),
        UniqueConstraint("organization_id", "provider", name="uq_provider_connections_org"),  # one per org (Batch 08)
        ForeignKeyConstraint(
            ["organization_id", "created_by"],
            ["users.organization_id", "users.id"],
            name="fk_provider_connections_org_creator",
        ),
        CheckConstraint("provider = 'meta_whatsapp'", name="provider"),
        CheckConstraint("mode IN ('contract_test', 'provider_test', 'production')", name="mode"),
        CheckConstraint("waba_id ~ '^[0-9]{5,20}$' AND phone_number_id ~ '^[0-9]{5,20}$'", name="meta_ids"),
        CheckConstraint("graph_version ~ '^v[0-9]{2}\\.0$'", name="graph_version"),
        CheckConstraint("credential_ref LIKE 'env:%'", name="credential_ref"),
        CheckConstraint("version >= 1", name="version_positive"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"))
    provider: Mapped[str] = mapped_column(String(32))
    waba_id: Mapped[str] = mapped_column(String(20))
    phone_number_id: Mapped[str] = mapped_column(String(20))
    graph_version: Mapped[str] = mapped_column(String(8))
    mode: Mapped[str] = mapped_column(String(16))
    enabled: Mapped[bool] = mapped_column(Boolean)
    credential_ref: Mapped[str] = mapped_column(String(80))
    created_by: Mapped[uuid.UUID]
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    version: Mapped[int] = mapped_column(Integer)


# --- P5.2 (ADR-027): signed webhook inbox. Inbound and status facts only; nothing here can send. ------------------

ITEM_TYPES = ("incoming_message", "delivery_status", "unsupported")
ITEM_STATES = ("pending", "processed", "quarantined", "failed")
STATUSES = ("sent", "delivered", "read", "failed", "unknown")


def _in(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{v}'" for v in values)


def _org_fk(cols: list[str], target: str, name: str) -> ForeignKeyConstraint:
    return ForeignKeyConstraint(["organization_id", *cols], [f"{target}.organization_id", f"{target}.id"], name=name)


class ProviderWebhookEnvelope(Base):
    """One verified (or quarantined) webhook delivery. Holds no tenant data: a body digest and counts only."""

    __tablename__ = "provider_webhook_envelopes"
    __table_args__ = (
        CheckConstraint("provider = 'meta_whatsapp'", name="provider"),
        CheckConstraint("parse_status IN ('accepted', 'quarantined')", name="parse_status"),
        CheckConstraint("body_sha256 ~ '^[0-9a-f]{64}$'", name="body_digest_format"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    provider: Mapped[str] = mapped_column(String(32))
    body_sha256: Mapped[str] = mapped_column(String(64))
    parse_status: Mapped[str] = mapped_column(String(16))
    quarantine_reason: Mapped[str | None] = mapped_column(String(64))
    counts_json: Mapped[dict[str, Any]] = mapped_column(JSONB)
    request_id: Mapped[str | None] = mapped_column(String(80))
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ProviderEventItem(Base):
    """One normalized item of a signed delivery, deduplicated per connection by its logical key."""

    __tablename__ = "provider_event_items"
    __table_args__ = (
        UniqueConstraint("organization_id", "id"),
        UniqueConstraint("provider_connection_id", "logical_key", name="uq_provider_event_items_logical"),
        _org_fk(["provider_connection_id"], "provider_connections", "fk_provider_event_items_org_connection"),
        ForeignKeyConstraint(
            ["envelope_id"], ["provider_webhook_envelopes.id"], name="fk_provider_event_items_envelope"
        ),
        CheckConstraint(f"item_type IN ({_in(ITEM_TYPES)})", name="item_type"),
        CheckConstraint(f"processing_status IN ({_in(ITEM_STATES)})", name="processing_status"),
        CheckConstraint("logical_key ~ '^[0-9a-f]{64}$'", name="logical_key_format"),
        CheckConstraint("attempts >= 0", name="attempts"),
        Index("ix_provider_event_items_pending", "provider_connection_id", "processing_status", "arrival_seq"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"))
    provider_connection_id: Mapped[uuid.UUID]
    envelope_id: Mapped[uuid.UUID]
    item_type: Mapped[str] = mapped_column(String(24))
    logical_key: Mapped[str] = mapped_column(String(64))
    provider_message_id: Mapped[str | None] = mapped_column(String(256))
    provider_timestamp: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    normalized_json: Mapped[dict[str, Any]] = mapped_column(JSONB)
    processing_status: Mapped[str] = mapped_column(String(16))
    error_class: Mapped[str | None] = mapped_column(String(40))
    attempts: Mapped[int] = mapped_column(Integer)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    # Database-assigned arrival order: items are processed in the order Meta delivered them (ties broken by the DB,
    # never by a random id).
    arrival_seq: Mapped[int] = mapped_column(BigInteger, Identity(always=True))


class ProviderStatusObservation(Base):
    """Every genuine status observation, append-only, in arrival order (the audit trail)."""

    __tablename__ = "provider_status_observations"
    __table_args__ = (
        UniqueConstraint("organization_id", "id"),
        UniqueConstraint("event_item_id", name="uq_provider_status_observations_item"),
        _org_fk(["provider_connection_id"], "provider_connections", "fk_provider_status_obs_org_connection"),
        _org_fk(["event_item_id"], "provider_event_items", "fk_provider_status_obs_org_item"),
        CheckConstraint(f"status IN ({_in(STATUSES)})", name="status"),
        Index("ix_provider_status_obs_message", "provider_connection_id", "provider_message_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"))
    provider_connection_id: Mapped[uuid.UUID]
    event_item_id: Mapped[uuid.UUID]
    provider_message_id: Mapped[str] = mapped_column(String(256))
    status: Mapped[str] = mapped_column(String(16))
    error_code: Mapped[str | None] = mapped_column(String(16))
    provider_timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ProviderMessageStatus(Base):
    """Projection per provider message id: never regresses; contradictions are flagged, not overwritten."""

    __tablename__ = "provider_message_status"
    __table_args__ = (
        UniqueConstraint("organization_id", "id"),
        UniqueConstraint("provider_connection_id", "provider_message_id", name="uq_provider_message_status_wamid"),
        _org_fk(["provider_connection_id"], "provider_connections", "fk_provider_message_status_org_connection"),
        CheckConstraint(f"status IN ({_in(STATUSES)})", name="status"),
        CheckConstraint("observations >= 1 AND version >= 1", name="counters"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"))
    provider_connection_id: Mapped[uuid.UUID]
    provider_message_id: Mapped[str] = mapped_column(String(256))
    status: Mapped[str] = mapped_column(String(16))
    last_provider_timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    conflict: Mapped[bool] = mapped_column(Boolean)
    conflict_reason: Mapped[str | None] = mapped_column(String(64))
    observations: Mapped[int] = mapped_column(Integer)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    version: Mapped[int] = mapped_column(Integer)


class ProviderInboundMessage(Base):
    """An authenticated inbound message: sender as a keyed digest, no text body kept (minimization)."""

    __tablename__ = "provider_inbound_messages"
    __table_args__ = (
        UniqueConstraint("organization_id", "id"),
        UniqueConstraint("provider_connection_id", "provider_message_id", name="uq_provider_inbound_wamid"),
        _org_fk(["provider_connection_id"], "provider_connections", "fk_provider_inbound_org_connection"),
        _org_fk(["contact_id"], "contacts", "fk_provider_inbound_org_contact"),
        _org_fk(["event_item_id"], "provider_event_items", "fk_provider_inbound_org_item"),
        CheckConstraint("kind IN ('text', 'image', 'document', 'interactive', 'unsupported')", name="kind"),
        CheckConstraint("assignment IN ('contact', 'unassigned')", name="assignment"),
        CheckConstraint("sender_digest ~ '^[0-9a-f]{64}$'", name="sender_digest_format"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"))
    provider_connection_id: Mapped[uuid.UUID]
    event_item_id: Mapped[uuid.UUID]
    provider_message_id: Mapped[str] = mapped_column(String(256))
    sender_key_id: Mapped[str] = mapped_column(String(16))
    sender_digest: Mapped[str] = mapped_column(String(64))
    sender_hint: Mapped[str] = mapped_column(String(40))
    contact_id: Mapped[uuid.UUID | None]
    assignment: Mapped[str] = mapped_column(String(16))
    kind: Mapped[str] = mapped_column(String(16))
    text_length: Mapped[int | None] = mapped_column(Integer)
    stop_signal: Mapped[bool] = mapped_column(Boolean)
    provider_timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ProviderServiceWindow(Base):
    """The latest *verified* inbound time per known contact: service-reply provenance, never marketing consent."""

    __tablename__ = "provider_service_windows"
    __table_args__ = (
        UniqueConstraint("organization_id", "id"),
        UniqueConstraint("organization_id", "contact_id", name="uq_provider_service_windows_contact"),
        _org_fk(["contact_id"], "contacts", "fk_provider_service_windows_org_contact"),
        _org_fk(["provider_connection_id"], "provider_connections", "fk_provider_service_windows_org_connection"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"))
    contact_id: Mapped[uuid.UUID]
    provider_connection_id: Mapped[uuid.UUID]
    last_verified_inbound_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    provider_message_id: Mapped[str] = mapped_column(String(256))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
