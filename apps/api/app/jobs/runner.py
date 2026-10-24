"""Postgres-authoritative job runner and outbox publisher (P1.5, ADR-011).

Guarantees (and their limits):
- At-least-once execution. A job's DB effect and its completion commit in one
  transaction guarded by the lease's fencing token, so a crash before
  acknowledgement rolls the effect back and a stale lease owner cannot complete.
  Logical exactly-once therefore holds only for *local DB effects*; it says
  nothing about future external providers (WhatsApp, email, HTTP).
- Time for leases/backoff is the database clock (`clock_timestamp()`), passed in
  explicitly so tests can control it; worker wall clocks are never trusted.
- Redis is optional: notifications only shorten the wait; DB polling always runs.
"""

import logging
import random
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Protocol

import psycopg
import redis.exceptions
import sqlalchemy.exc
from pydantic import ValidationError
from redis import Redis
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session, sessionmaker

from app.core.request_context import accept_request_id, bound_request_id
from app.jobs import registry
from app.jobs.models import Job, JobStatus

logger = logging.getLogger("app.jobs")

LEASE = timedelta(seconds=60)
OUTBOX_LEASE = timedelta(seconds=30)
BACKOFF_BASE = timedelta(seconds=2)
BACKOFF_CAP = timedelta(minutes=5)
JITTER = 0.2
WAKE_KEY = "hermecious:jobs:wake"
WAKE_LIST_MAX = 1000

_DB_TRANSIENT = (psycopg.OperationalError, sqlalchemy.exc.OperationalError, sqlalchemy.exc.DisconnectionError)


class LeaseLost(Exception):
    """The fencing token no longer matches: another worker owns (or finished) this job."""


@dataclass(frozen=True)
class ClaimedJob:
    id: uuid.UUID
    organization_id: uuid.UUID
    job_type: str
    schema_version: int
    payload: dict[str, Any]
    attempts: int
    max_attempts: int
    lease_token: uuid.UUID
    correlation_id: str | None


def db_now(db: Session) -> datetime:
    value = db.scalar(select(func.clock_timestamp()))
    if not isinstance(value, datetime):
        raise RuntimeError("database clock unavailable")
    return value


def backoff(attempt: int, rng: random.Random) -> timedelta:
    """Exponential, capped, with bounded jitter (±20%)."""
    base: timedelta = min(BACKOFF_BASE * (2 ** max(attempt - 1, 0)), BACKOFF_CAP)
    return base * (1 + rng.uniform(-JITTER, JITTER))


def claim_due_jobs(db: Session, *, worker_id: str, max_items: int, now: datetime) -> list[ClaimedJob]:
    """Dead-letter exhausted expired leases, then claim due jobs with SKIP LOCKED. Commits."""
    db.execute(
        text(
            "UPDATE jobs SET status = 'dead', last_error_class = 'lease_expired', finished_at = :now,"
            " lease_owner = NULL, lease_token = NULL, lease_expires_at = NULL, updated_at = :now"
            " WHERE status = 'running' AND lease_expires_at <= :now AND attempts >= max_attempts"
        ),
        {"now": now},
    )
    rows = db.execute(
        text(
            "WITH due AS ("
            "  SELECT id FROM jobs"
            "  WHERE (status IN ('pending', 'retry_wait') AND available_at <= :now)"
            "     OR (status = 'running' AND lease_expires_at <= :now)"
            "  ORDER BY available_at, id LIMIT :limit FOR UPDATE SKIP LOCKED)"
            " UPDATE jobs SET status = 'running', attempts = jobs.attempts + 1, lease_owner = :worker,"
            "   lease_token = gen_random_uuid(), lease_expires_at = :now + :lease,"
            "   started_at = coalesce(jobs.started_at, :now), updated_at = :now"
            " FROM due WHERE jobs.id = due.id"
            " RETURNING jobs.id, jobs.organization_id, jobs.job_type, jobs.job_schema_version, jobs.payload_json,"
            "   jobs.attempts, jobs.max_attempts, jobs.lease_token, jobs.correlation_id"
        ),
        {"now": now, "limit": max_items, "worker": worker_id, "lease": LEASE},
    ).all()
    db.commit()
    return [ClaimedJob(*row) for row in rows]


def complete_job(db: Session, *, job_id: uuid.UUID, lease_token: uuid.UUID, result_digest: str, now: datetime) -> None:
    """Fenced success in the caller's transaction (the same one as the job's effect)."""
    result = db.execute(
        text(
            "UPDATE jobs SET status = 'succeeded', finished_at = :now, result_digest = :digest,"
            " lease_owner = NULL, lease_token = NULL, lease_expires_at = NULL, last_error_class = NULL,"
            " updated_at = :now WHERE id = :id AND lease_token = :token AND status = 'running'"
        ),
        {"now": now, "digest": result_digest, "id": job_id, "token": lease_token},
    )
    if getattr(result, "rowcount", 0) != 1:
        raise LeaseLost()


def fail_job(
    db: Session,
    *,
    job_id: uuid.UUID,
    lease_token: uuid.UUID,
    error_class: str,
    retryable: bool,
    now: datetime,
    rng: random.Random,
) -> str | None:
    """Fenced failure: retry_wait with backoff while attempts remain, else dead. Commits. None if lease lost."""
    job = db.scalar(select(Job).where(Job.id == job_id, Job.lease_token == lease_token).with_for_update())
    if job is None or job.status != JobStatus.RUNNING:
        db.rollback()
        return None
    if retryable and job.attempts < job.max_attempts:
        job.status = JobStatus.RETRY_WAIT
        job.available_at = now + backoff(job.attempts, rng)
    else:
        job.status = JobStatus.DEAD
        job.finished_at = now
        error_class = error_class if not retryable else "retries_exhausted"
    job.last_error_class = error_class
    job.lease_owner = job.lease_token = job.lease_expires_at = None
    job.updated_at = now
    db.commit()
    return job.status


@dataclass(frozen=True)
class Outcome:
    job_id: uuid.UUID
    status: str  # succeeded | retry_wait | dead | lease_lost


def execute(
    factory: sessionmaker[Session],
    job: ClaimedJob,
    *,
    environment: str,
    now_fn: Callable[[Session], datetime],
    rng: random.Random,
) -> Outcome:
    """Run one claimed job: effect + fenced completion in a single transaction."""
    trace = accept_request_id(job.correlation_id, prefix="job")
    with bound_request_id(trace), factory() as db:
        context = {"job_id": str(job.id), "job_type": job.job_type, "attempt": job.attempts}
        error_class, retryable = "unexpected_error", True
        try:
            spec = registry.resolve(job.job_type, job.schema_version, environment)
            payload = spec.payload_model.model_validate(job.payload)
            now = now_fn(db)
            ctx = registry.JobContext(job.id, job.organization_id, job.attempts, now, environment, job.max_attempts)
            result = spec.handler(db, ctx, payload)
            complete_job(db, job_id=job.id, lease_token=job.lease_token, result_digest=registry.digest(result), now=now)
            db.commit()
            logger.info("job.succeeded", extra={"context": context})
            return Outcome(job.id, JobStatus.SUCCEEDED)
        except LeaseLost:
            db.rollback()  # our effect is undone; the current lease owner's result stands
            logger.warning("job.lease_lost", extra={"context": context})
            return Outcome(job.id, "lease_lost")
        except registry.PermanentJobError as exc:
            error_class, retryable = exc.error_class, False
        except (registry.PayloadRejected, ValidationError):
            error_class, retryable = "invalid_payload", False
        except registry.TransientJobError as exc:
            error_class = exc.error_class
        except _DB_TRANSIENT:
            error_class = "database_unavailable"
        except Exception:  # unknown failures retry, bounded by max_attempts; details stay out of the DB
            logger.exception("job.unexpected_error", extra={"context": context})
        db.rollback()
        status = fail_job(
            db,
            job_id=job.id,
            lease_token=job.lease_token,
            error_class=error_class,
            retryable=retryable,
            now=now_fn(db),
            rng=rng,
        )
        logger.warning("job.failed", extra={"context": {**context, "error_class": error_class, "status": status}})
        return Outcome(job.id, status or "lease_lost")


class NotificationSink(Protocol):
    name: str

    def notify(self, event_id: uuid.UUID, event_type: str) -> None: ...


class NoSink:
    """No external notification configured: events are marked dispatched to 'none'; DB polling does the work."""

    name = "none"

    def notify(self, event_id: uuid.UUID, event_type: str) -> None:
        return None


class RedisSink:
    name = "redis"

    def __init__(self, client: Redis) -> None:
        self.client = client

    def notify(self, event_id: uuid.UUID, event_type: str) -> None:
        pipe = self.client.pipeline()
        pipe.lpush(WAKE_KEY, str(event_id))  # identifiers only, never payloads
        pipe.ltrim(WAKE_KEY, 0, WAKE_LIST_MAX - 1)
        pipe.execute()


def publish_outbox(
    factory: sessionmaker[Session],
    *,
    worker_id: str,
    sink: NotificationSink,
    max_items: int,
    now_fn: Callable[[Session], datetime],
    rng: random.Random,
) -> dict[str, int]:
    """Deliver undispatched events to the sink. `dispatched_at` = notification delivered, not job done."""
    with factory() as db:
        now = now_fn(db)
        rows = db.execute(
            text(
                "WITH due AS ("
                "  SELECT id FROM outbox_events WHERE dispatched_at IS NULL AND next_attempt_at <= :now"
                "    AND (lease_expires_at IS NULL OR lease_expires_at <= :now)"
                "  ORDER BY next_attempt_at, id LIMIT :limit FOR UPDATE SKIP LOCKED)"
                " UPDATE outbox_events SET lease_owner = :worker, lease_expires_at = :now + :lease"
                " FROM due WHERE outbox_events.id = due.id"
                " RETURNING outbox_events.id, outbox_events.event_type, outbox_events.attempts"
            ),
            {"now": now, "limit": max_items, "worker": worker_id, "lease": OUTBOX_LEASE},
        ).all()
        db.commit()
        counts = {"dispatched": 0, "failed": 0}
        for event_id, event_type, attempts in rows:
            try:
                sink.notify(event_id, event_type)
            except (redis.exceptions.RedisError, OSError) as exc:
                db.execute(
                    text(
                        "UPDATE outbox_events SET attempts = attempts + 1, next_attempt_at = :next,"
                        " last_error_class = :error, lease_owner = NULL, lease_expires_at = NULL"
                        " WHERE id = :id AND lease_owner = :worker AND dispatched_at IS NULL"
                    ),
                    {
                        "next": now + backoff(attempts + 1, rng),  # grows per failed delivery, capped
                        "error": "sink_unavailable",
                        "id": event_id,
                        "worker": worker_id,
                    },
                )
                db.commit()
                counts["failed"] += 1
                logger.warning("outbox.notify_failed", extra={"context": {"error_class": type(exc).__name__}})
                continue
            db.execute(
                text(
                    "UPDATE outbox_events SET dispatched_at = :now, dispatch_sink = :sink, attempts = attempts + 1,"
                    " last_error_class = NULL, lease_owner = NULL, lease_expires_at = NULL"
                    " WHERE id = :id AND lease_owner = :worker AND dispatched_at IS NULL"
                ),
                {"now": now_fn(db), "sink": sink.name, "id": event_id, "worker": worker_id},
            )
            db.commit()
            counts["dispatched"] += 1
        return counts


def queue_metrics(db: Session, now: datetime, organization_id: uuid.UUID | None = None) -> dict[str, Any]:
    """Backlog and dead-letter visibility without payloads (all organizations unless one is given)."""
    scope = [Job.organization_id == organization_id] if organization_id else []
    counts = dict(db.execute(select(Job.status, func.count()).where(*scope).group_by(Job.status)).all())
    oldest = db.scalar(
        select(func.min(Job.available_at)).where(Job.status.in_([JobStatus.PENDING, JobStatus.RETRY_WAIT]), *scope)
    )
    undispatched = (
        db.scalar(
            text(
                "SELECT count(*) FROM outbox_events WHERE dispatched_at IS NULL"
                " AND (CAST(:org AS uuid) IS NULL OR organization_id = CAST(:org AS uuid))"
            ),
            {"org": organization_id},
        )
        or 0
    )
    return {
        **{status.value: int(counts.get(status.value, 0)) for status in JobStatus},
        "oldest_due_seconds": max(0, int((now - oldest).total_seconds())) if oldest else 0,
        "undispatched_events": int(undispatched),
    }


class JobRunner:
    """One bounded worker loop: publish outbox -> claim due jobs -> execute -> wait (Redis wake or poll)."""

    def __init__(
        self,
        factory: sessionmaker[Session],
        *,
        worker_id: str,
        environment: str,
        sink: NotificationSink,
        wake_client: Redis | None,
        heartbeat: Callable[[], None],
        batch: int = 5,
        poll_seconds: int = 2,
        metrics_every_seconds: int = 30,
        now_fn: Callable[[Session], datetime] = db_now,
        rng: random.Random | None = None,
    ) -> None:
        self.factory = factory
        self.worker_id = worker_id
        self.environment = environment
        self.sink = sink
        self.wake_client = wake_client
        self.heartbeat = heartbeat
        self.batch = batch
        self.poll_seconds = poll_seconds
        self.metrics_every = timedelta(seconds=metrics_every_seconds)
        self.now_fn = now_fn
        self.rng = rng or random.Random()  # noqa: S311  # jitter only, not security
        self._last_metrics: datetime | None = None

    def run_once(self) -> list[Outcome]:
        publish_outbox(
            self.factory,
            worker_id=self.worker_id,
            sink=self.sink,
            max_items=self.batch * 4,
            now_fn=self.now_fn,
            rng=self.rng,
        )
        with self.factory() as db:
            claimed = claim_due_jobs(db, worker_id=self.worker_id, max_items=self.batch, now=self.now_fn(db))
            self._metrics(db)
        return [
            execute(self.factory, job, environment=self.environment, now_fn=self.now_fn, rng=self.rng)
            for job in claimed
        ]

    def _metrics(self, db: Session) -> None:
        now = self.now_fn(db)
        if self._last_metrics is not None and now - self._last_metrics < self.metrics_every:
            return
        self._last_metrics = now
        logger.info("jobs.metrics", extra={"context": queue_metrics(db, now)})

    def _wait(self, stop: Any) -> None:
        if self.wake_client is not None:
            try:
                self.wake_client.blpop([WAKE_KEY], timeout=self.poll_seconds)
                return
            except redis.exceptions.RedisError:
                pass  # Redis is optional: fall back to plain DB polling
        stop.wait(self.poll_seconds)

    def run_forever(self, stop: Any) -> None:
        logger.info("worker.started", extra={"context": {"queue": "postgres"}})
        while not stop.is_set():
            outcomes: list[Outcome] = []
            try:
                outcomes = self.run_once()
            except _DB_TRANSIENT as exc:
                logger.warning("worker.database_unavailable", extra={"context": {"error_class": type(exc).__name__}})
            except sqlalchemy.exc.ProgrammingError:
                # Schema not migrated yet: keep waiting (no crash loop) but do NOT heartbeat,
                # so the container stays unhealthy until migrations are applied.
                logger.warning("worker.schema_not_ready", extra={"context": {"reason": "run alembic upgrade head"}})
                self._wait(stop)
                continue
            self.heartbeat()
            if not outcomes:
                self._wait(stop)
        logger.info("worker.stopped")
