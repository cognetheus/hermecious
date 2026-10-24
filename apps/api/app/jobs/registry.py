"""Allowlisted job types: (job_type, schema_version) -> payload model + handler (P1.5).

Nothing else can run. There is no way to enqueue a class name, function path,
shell command or unknown version; payloads are typed, bounded and must not
carry credentials or contact data.
"""

import hashlib
import json
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.accounts.models import Account, AccountAuditSnapshot, AccountFact
from app.core.logging import scrub_text

MAX_PAYLOAD_BYTES = 16 * 1024
_SECRET_KEYS = {"password", "passwd", "secret", "token", "api_key", "apikey", "authorization", "cookie", "session"}


class JobError(Exception):
    """Base for classified handler failures. `error_class` is a safe, fixed taxonomy label."""

    error_class = "job_error"

    def __init__(self, error_class: str | None = None) -> None:
        super().__init__(error_class or self.error_class)
        if error_class:
            self.error_class = error_class


class TransientJobError(JobError):
    error_class = "transient_error"


class PermanentJobError(JobError):
    error_class = "permanent_error"


class PayloadRejected(ValueError):
    """Enqueue refused: unknown type/version, invalid, oversized or sensitive payload. Message is safe."""


@dataclass(frozen=True)
class JobContext:
    job_id: uuid.UUID
    organization_id: uuid.UUID
    attempt: int
    now: datetime
    environment: str | None = None  # P2.4: handlers that select providers re-check policy for this environment
    max_attempts: int = 1


class _Payload(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class NoopPayload(_Payload):
    note: str | None = Field(default=None, max_length=100)


class AccountSnapshotPayload(_Payload):
    account_id: uuid.UUID


Handler = Callable[[Session, JobContext, Any], dict[str, Any]]


@dataclass(frozen=True)
class JobSpec:
    job_type: str
    version: int
    payload_model: type[_Payload]
    handler: Handler
    max_attempts: int
    environments: frozenset[str]


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def digest(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _noop(db: Session, ctx: JobContext, payload: NoopPayload) -> dict[str, Any]:
    return {"noop": True}


def _account_snapshot(db: Session, ctx: JobContext, payload: AccountSnapshotPayload) -> dict[str, Any]:
    """DB-only effect: one sanitized count snapshot per job (UNIQUE(organization_id, job_id))."""
    account = db.scalar(
        select(Account).where(Account.id == payload.account_id, Account.organization_id == ctx.organization_id)
    )
    if account is None:
        raise PermanentJobError("account_not_found")
    scoped = (AccountFact.organization_id == ctx.organization_id) & (AccountFact.account_id == account.id)
    total = db.scalar(select(func.count()).select_from(AccountFact).where(scoped)) or 0
    superseded = (
        db.scalar(
            select(func.count())
            .select_from(AccountFact)
            .where(scoped, AccountFact.id.in_(select(AccountFact.supersedes_fact_id).where(scoped)))
        )
        or 0
    )
    summary = {"account_version": account.version, "fact_count": total, "current_fact_count": total - superseded}
    db.execute(
        insert(AccountAuditSnapshot)
        .values(
            organization_id=ctx.organization_id,
            account_id=account.id,
            job_id=ctx.job_id,
            snapshot_digest=digest(summary),
            taken_at=ctx.now,
            **summary,
        )
        .on_conflict_do_nothing(index_elements=["organization_id", "job_id"])
    )
    return summary


def _discovery_run(db: Session, ctx: JobContext, payload: Any) -> dict[str, Any]:
    from app.discovery.runs import handle_run_job  # noqa: PLC0415  # avoids an import cycle with app.discovery

    result: dict[str, Any] = handle_run_job(db, ctx, payload)
    return result


class DiscoveryRunPayload(_Payload):
    """`discovery.run` v1 (P2.4): the run row holds the budget and policy snapshot; the payload only names it."""

    run_id: uuid.UUID


REGISTRY: dict[tuple[str, int], JobSpec] = {
    ("diagnostic.noop", 1): JobSpec(
        "diagnostic.noop", 1, NoopPayload, _noop, max_attempts=3, environments=frozenset({"development", "test"})
    ),
    ("account.audit_snapshot", 1): JobSpec(
        "account.audit_snapshot",
        1,
        AccountSnapshotPayload,
        _account_snapshot,
        max_attempts=5,
        environments=frozenset({"development", "test", "production"}),
    ),
    ("discovery.run", 1): JobSpec(
        "discovery.run",
        1,
        DiscoveryRunPayload,
        _discovery_run,
        max_attempts=3,
        environments=frozenset({"development", "test", "production"}),
    ),
}


def resolve(job_type: str, version: int, environment: str) -> JobSpec:
    spec = REGISTRY.get((job_type, version))
    if spec is None:
        raise PayloadRejected("job type or schema version is not registered")
    if environment not in spec.environments:
        raise PayloadRejected("job type is not enabled in this environment")
    return spec


def _check_sensitive(value: Any, key: str | None = None) -> None:
    if key is not None and key.lower() in _SECRET_KEYS:
        raise PayloadRejected("payload must not contain credential fields")
    if isinstance(value, dict):
        for k, v in value.items():
            _check_sensitive(v, str(k))
    elif isinstance(value, list):
        for v in value:
            _check_sensitive(v)
    elif isinstance(value, str) and scrub_text(value, limit=MAX_PAYLOAD_BYTES) != value:
        # Anything the log scrubber would redact (credentials, emails, phones) is refused outright.
        raise PayloadRejected("payload must not contain credentials or contact data")


def validate_payload(spec: JobSpec, payload: Any) -> dict[str, Any]:
    """Typed, bounded, non-sensitive canonical payload, or PayloadRejected."""
    if not isinstance(payload, dict):
        raise PayloadRejected("payload must be an object")
    if len(canonical_json(payload).encode("utf-8")) > MAX_PAYLOAD_BYTES:
        raise PayloadRejected("payload is too large")
    _check_sensitive(payload)
    try:
        model = spec.payload_model.model_validate(payload)
    except ValidationError:
        raise PayloadRejected("payload does not match the job schema") from None
    return model.model_dump(mode="json")
