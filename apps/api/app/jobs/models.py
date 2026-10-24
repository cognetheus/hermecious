"""Durable jobs and transactional outbox (P1.5, ADR-011). PostgreSQL is the only authority."""

import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, String, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.persistence.base import Base


class JobStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    RETRY_WAIT = "retry_wait"
    SUCCEEDED = "succeeded"
    DEAD = "dead"
    CANCELLED = "cancelled"


TERMINAL = frozenset({JobStatus.SUCCEEDED, JobStatus.DEAD, JobStatus.CANCELLED})


class Job(Base):
    __tablename__ = "jobs"
    __table_args__ = (
        UniqueConstraint("organization_id", "job_type", "idempotency_key"),
        UniqueConstraint("organization_id", "id"),
        CheckConstraint(
            "status IN ('pending', 'running', 'retry_wait', 'succeeded', 'dead', 'cancelled')", name="status"
        ),
        CheckConstraint("job_type ~ '^[a-z][a-z0-9_]*\\.[a-z][a-z0-9_]*$'", name="job_type_format"),
        CheckConstraint("idempotency_key ~ '^[A-Za-z0-9._:-]{1,200}$'", name="idempotency_key_format"),
        CheckConstraint("max_attempts BETWEEN 1 AND 10", name="max_attempts_range"),
        CheckConstraint("attempts >= 0", name="attempts_non_negative"),
        CheckConstraint("payload_digest ~ '^[0-9a-f]{64}$'", name="payload_digest_format"),
        CheckConstraint(
            "status <> 'running'"
            " OR (lease_owner IS NOT NULL AND lease_token IS NOT NULL AND lease_expires_at IS NOT NULL)",
            name="running_has_lease",
        ),
        CheckConstraint(
            "status NOT IN ('succeeded', 'dead', 'cancelled') OR finished_at IS NOT NULL", name="terminal_has_finish"
        ),
        CheckConstraint(
            "last_error_class IS NULL OR last_error_class ~ '^[a-z][a-z0-9_]{1,63}$'", name="error_class_format"
        ),
        Index(
            "ix_jobs_claimable",
            "status",
            "available_at",
            "lease_expires_at",
            "id",
            postgresql_where=text("status IN ('pending', 'retry_wait', 'running')"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"))
    job_type: Mapped[str] = mapped_column(String(80))
    job_schema_version: Mapped[int] = mapped_column(Integer, server_default="1")
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSONB)
    payload_digest: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(16))
    attempts: Mapped[int] = mapped_column(Integer, server_default="0")
    max_attempts: Mapped[int] = mapped_column(Integer)
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    lease_owner: Mapped[str | None] = mapped_column(String(120))
    # Fencing token: a new value on every claim; completion/failure must present it.
    lease_token: Mapped[uuid.UUID | None]
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error_class: Mapped[str | None] = mapped_column(String(64))
    idempotency_key: Mapped[str] = mapped_column(String(200))
    correlation_id: Mapped[str | None] = mapped_column(String(64))
    result_digest: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class OutboxEvent(Base):
    __tablename__ = "outbox_events"
    __table_args__ = (
        UniqueConstraint("organization_id", "event_type", "idempotency_key"),
        CheckConstraint("event_type ~ '^[a-z][a-z0-9_]*\\.[a-z][a-z0-9_]*$'", name="event_type_format"),
        CheckConstraint("aggregate_type ~ '^[a-z][a-z0-9_]{1,39}$'", name="aggregate_type_format"),
        CheckConstraint("idempotency_key ~ '^[A-Za-z0-9._:-]{1,200}$'", name="idempotency_key_format"),
        CheckConstraint("attempts >= 0", name="attempts_non_negative"),
        CheckConstraint("(dispatched_at IS NULL) = (dispatch_sink IS NULL)", name="dispatch_has_sink"),
        CheckConstraint("dispatch_sink IS NULL OR dispatch_sink IN ('redis', 'none')", name="dispatch_sink_values"),
        CheckConstraint(
            "last_error_class IS NULL OR last_error_class ~ '^[a-z][a-z0-9_]{1,63}$'", name="error_class_format"
        ),
        Index(
            "ix_outbox_events_undispatched",
            "next_attempt_at",
            "id",
            postgresql_where=text("dispatched_at IS NULL"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"))
    aggregate_type: Mapped[str] = mapped_column(String(40))
    aggregate_id: Mapped[uuid.UUID]
    event_type: Mapped[str] = mapped_column(String(80))
    event_schema_version: Mapped[int] = mapped_column(Integer, server_default="1")
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSONB)
    idempotency_key: Mapped[str] = mapped_column(String(200))
    # Notification delivered to `dispatch_sink` ('none' = no external sink configured).
    # Never means the related job ran.
    dispatched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    dispatch_sink: Mapped[str | None] = mapped_column(String(16))
    attempts: Mapped[int] = mapped_column(Integer, server_default="0")
    next_attempt_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    lease_owner: Mapped[str | None] = mapped_column(String(120))
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error_class: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
