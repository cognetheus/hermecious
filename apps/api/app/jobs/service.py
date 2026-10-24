"""Transactional enqueue and outbox recording (P1.5).

Both functions write inside the *caller's* transaction and never commit: the
domain change, the job and its outbox event commit together or not at all.
"""

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.core.clock import Clock
from app.core.errors import Conflict, InvalidRequest
from app.core.request_context import current_request_id
from app.jobs import registry
from app.jobs.models import Job, JobStatus, OutboxEvent

IDEMPOTENCY_CONFLICT = "Idempotency key was already used with a different payload or schema version"


@dataclass(frozen=True)
class JobReceipt:
    job_id: uuid.UUID
    status: str
    created: bool


def record_outbox_event(
    db: Session,
    *,
    organization_id: uuid.UUID,
    aggregate_type: str,
    aggregate_id: uuid.UUID,
    event_type: str,
    event_version: int,
    payload: dict[str, Any],
    idempotency_key: str,
    clock: Clock,
) -> uuid.UUID:
    """Insert once per (organization, event_type, idempotency_key); a replay returns the same event id."""
    now = clock.now()
    event_id = db.scalar(
        insert(OutboxEvent)
        .values(
            id=uuid.uuid4(),
            organization_id=organization_id,
            aggregate_type=aggregate_type,
            aggregate_id=aggregate_id,
            event_type=event_type,
            event_schema_version=event_version,
            payload_json=payload,
            idempotency_key=idempotency_key,
            next_attempt_at=now,
            created_at=now,
        )
        .on_conflict_do_nothing(index_elements=["organization_id", "event_type", "idempotency_key"])
        .returning(OutboxEvent.id)
    )
    if event_id is None:
        event_id = db.scalar(
            select(OutboxEvent.id).where(
                OutboxEvent.organization_id == organization_id,
                OutboxEvent.event_type == event_type,
                OutboxEvent.idempotency_key == idempotency_key,
            )
        )
    assert event_id is not None  # noqa: S101  # row exists: either inserted now or by the conflicting insert
    return event_id


def enqueue_job(
    db: Session,
    *,
    organization_id: uuid.UUID,
    environment: str,
    job_type: str,
    schema_version: int,
    payload: dict[str, Any],
    idempotency_key: str,
    clock: Clock,
    available_at: datetime | None = None,
) -> JobReceipt:
    """Durable intent in the caller's transaction. Exact replay -> same receipt; mismatch -> Conflict."""
    try:
        spec = registry.resolve(job_type, schema_version, environment)
        clean = registry.validate_payload(spec, payload)
    except registry.PayloadRejected as exc:
        raise InvalidRequest(str(exc)) from None
    payload_digest = registry.digest(clean)
    now = clock.now()
    job_id = db.scalar(
        insert(Job)
        .values(
            id=uuid.uuid4(),
            organization_id=organization_id,
            job_type=job_type,
            job_schema_version=schema_version,
            payload_json=clean,
            payload_digest=payload_digest,
            status=JobStatus.PENDING,
            attempts=0,
            max_attempts=spec.max_attempts,
            available_at=available_at or now,
            idempotency_key=idempotency_key,
            correlation_id=current_request_id(),
            created_at=now,
            updated_at=now,
        )
        .on_conflict_do_nothing(index_elements=["organization_id", "job_type", "idempotency_key"])
        .returning(Job.id)
    )
    if job_id is not None:
        record_outbox_event(
            db,
            organization_id=organization_id,
            aggregate_type="job",
            aggregate_id=job_id,
            event_type="job.enqueued",
            event_version=1,
            payload={"job_id": str(job_id), "job_type": job_type},
            idempotency_key=str(job_id),
            clock=clock,
        )
        return JobReceipt(job_id=job_id, status=JobStatus.PENDING, created=True)

    existing = db.scalar(
        select(Job).where(
            Job.organization_id == organization_id,
            Job.job_type == job_type,
            Job.idempotency_key == idempotency_key,
        )
    )
    if existing is None:  # concurrent inserter rolled back after we saw its conflict; caller may retry
        raise Conflict("Concurrent enqueue did not commit; retry")
    if existing.payload_digest != payload_digest or existing.job_schema_version != schema_version:
        raise Conflict(IDEMPOTENCY_CONFLICT)
    return JobReceipt(job_id=existing.id, status=existing.status, created=False)
