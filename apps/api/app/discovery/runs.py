"""Operator discovery runs and reviewer admission (P2.4, ADR-015).

A run is requested by an owner/operator, committed atomically with its
`discovery.run` v1 job (P1.5 outbox), and executed by the worker with the
P2.1/P2.2 runner and the P2.3 resolver. Budgets are snapshotted at enqueue and
enforced again by the worker and the runner. Policy is re-checked at
execution and before every adapter call. `completed` means the bounded run
finished, never that Lahore was searched exhaustively.

Admission is always an explicit reviewer action:
- `accept_new` creates one P1.4 account (status `discovered`: research pending, nothing qualified);
- `attach_existing` requires a P2.3 reviewed same-campus link;
- `reject` and `defer` change review state only.

Decisions are idempotent per key; concurrent accepts converge on one account.
"""

import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import and_, case, func, or_, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.accounts import management, policy
from app.accounts import service as account_service
from app.accounts.models import Account, AccountAlias, SourceRecord, Vertical
from app.auth.dependencies import ROLE_CAPABILITIES, Capability
from app.auth.models import Role, User
from app.auth.service import Actor
from app.core.clock import Clock, FixedClock
from app.core.errors import Conflict, InvalidRequest, NotFound
from app.core.request_context import current_request_id
from app.core.settings import Settings, load_settings
from app.discovery import osm, registry, seed_import
from app.discovery.contracts import Operation, SourceAdapter, SourceDescriptor, SourceQuery
from app.discovery.fixture import FixtureLahoreSchoolsAdapter
from app.discovery.models import (
    RUN_TERMINAL,
    DiscoveryCandidate,
    DiscoveryReviewDecision,
    DiscoveryRun,
    DiscoveryRunCandidate,
    SourceImport,
)
from app.discovery.runner import DiscoveryBudget, run_discovery
from app.jobs import registry as job_registry
from app.jobs import service as job_service
from app.resolution import service as resolution_service
from app.resolution.models import CandidateAccountLink, IdentitySuggestion

JOB_TYPE, JOB_VERSION, MAX_ATTEMPTS = "discovery.run", 1, 3
CITY, VERTICAL = "Lahore", "schools"
MAX_RUN_SECONDS = 45  # below the 60 s P1.5 job lease, so a healthy run never outlives its lease
ReviewAction = Literal["accept_new", "attach_existing", "reject", "defer"]
REVIEW_TRANSITIONS: dict[str, dict[str, str]] = {
    "accept_new": {"pending": "accepted", "deferred": "accepted"},
    "attach_existing": {"pending": "accepted", "deferred": "accepted"},
    "reject": {"pending": "rejected", "deferred": "rejected"},
    "defer": {"pending": "deferred"},
}


class RunBudget(BaseModel):
    """Operator budget: may only tighten the platform ceilings (validated again by DiscoveryBudget)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    max_candidates: int = Field(default=30, ge=1, le=30)
    max_search_pages: int = Field(default=5, ge=1, le=5)
    max_fetches: int = Field(default=20, ge=0, le=20)
    max_seconds: int = Field(default=MAX_RUN_SECONDS, ge=5, le=MAX_RUN_SECONDS)
    seed_import_id: uuid.UUID | None = None  # only for the operator CSV source: which staged import to review

    def dump(self) -> dict[str, Any]:
        return self.model_dump(mode="json", exclude_none=True)


@dataclass(frozen=True)
class SourceOption:
    provider: str
    label: str
    area_label: str
    synthetic: bool
    descriptor: SourceDescriptor


def _options(settings: Settings) -> list[SourceOption]:
    fixture = registry.DESCRIPTORS[registry.FIXTURE_PROVIDER]
    citation = settings.osm_bbox_citation or "not configured"
    return [
        SourceOption(registry.FIXTURE_PROVIDER, "Synthetic fixture (offline, fictional records)",
                     "Lahore: synthetic fixture dataset", True, fixture),
        SourceOption(osm.PROVIDER, "OpenStreetMap school listings (Overpass)",
                     f"Lahore: operator-configured box ({citation})", False, osm.descriptor_from_settings(settings)),
        SourceOption(seed_import.PROVIDER, "Operator CSV seed import (user-provided, not independently verified)",
                     "Lahore: operator-supplied list", False, seed_import.DESCRIPTOR),
    ]  # fmt: skip


def source_refusal(option: SourceOption, environment: str, now: datetime) -> str | None:
    try:
        registry.check_descriptor(option.descriptor, environment, now=now)
        if option.provider == seed_import.PROVIDER:  # nothing is fetched: rows were staged by an import
            registry.require_operation(option.descriptor, Operation.STORE_METADATA)
            return None
        registry.require_operation(option.descriptor, Operation.SEARCH)
        registry.require_operation(option.descriptor, Operation.FETCH)
    except registry.SourcePolicyError as exc:
        return exc.reason
    return None


def available_sources(settings: Settings, now: datetime) -> list[SourceOption]:
    return [o for o in _options(settings) if source_refusal(o, settings.environment, now) is None]


def build_adapter(provider: str, settings: Settings) -> SourceAdapter:
    """The only place a worker turns a provider id into an adapter (tests replace this hook)."""
    if provider == registry.FIXTURE_PROVIDER:
        return FixtureLahoreSchoolsAdapter()
    if provider == osm.PROVIDER:
        return osm.adapter_from_settings(settings)
    raise registry.SourcePolicyError("provider_disabled")


SETTINGS: Callable[[], Settings] = load_settings  # worker-side settings (tests replace this hook)


# --- create / cancel --------------------------------------------------------------------------------------


def _lock_run(db: Session, org: uuid.UUID, run_id: uuid.UUID) -> DiscoveryRun | None:
    return db.scalar(
        select(DiscoveryRun)
        .where(DiscoveryRun.organization_id == org, DiscoveryRun.id == run_id)
        .with_for_update()
        .execution_options(populate_existing=True)  # sessions keep objects after commit: never read a stale run
    )


def create_run(
    db: Session, *, actor: Actor, clock: Clock, settings: Settings, provider: str, budget: RunBudget,
    idempotency_key: str,
) -> tuple[DiscoveryRun, bool]:  # fmt: skip
    """Returns (run, created). Same key + same request replays; same key + different request is 409."""
    account_service._require(actor, Capability.MUTATE)
    org = actor.organization_id
    request = {"provider": provider, "budget": budget.dump(), "city": CITY, "vertical": VERTICAL}
    digest = job_registry.digest(request)

    def replay() -> DiscoveryRun | None:
        prior = db.scalar(
            select(DiscoveryRun).where(
                DiscoveryRun.organization_id == org, DiscoveryRun.idempotency_key == idempotency_key
            )
        )
        if prior is not None and prior.request_digest != digest:
            raise Conflict("idempotency_key was already used for a different run request")
        return prior

    prior = replay()
    if prior is not None:
        return prior, False
    now = clock.now()
    option = next((o for o in _options(settings) if o.provider == provider), None)
    if option is None:
        raise InvalidRequest("unknown_provider")
    refusal = source_refusal(option, settings.environment, now)
    if refusal is not None:
        raise InvalidRequest(f"source is not available: {refusal}")  # preflight: nothing is written
    descriptor = option.descriptor
    if budget.max_candidates > descriptor.result_limit:
        raise InvalidRequest("max_candidates exceeds this source's limit")
    if (provider == seed_import.PROVIDER) != (budget.seed_import_id is not None):
        raise InvalidRequest("seed_import_id is required for, and only for, the operator CSV source")
    if (
        budget.seed_import_id is not None
        and db.scalar(
            select(SourceImport.id).where(
                SourceImport.organization_id == org,
                SourceImport.id == budget.seed_import_id,
                SourceImport.provider == seed_import.PROVIDER,
            )
        )
        is None
    ):
        raise NotFound()
    run = DiscoveryRun(
        organization_id=org, created_by=actor.user_id, vertical_slug=VERTICAL, city=CITY,
        area_label=option.area_label[:300], provider=provider, adapter_version=descriptor.adapter_version,
        rights_policy_version=str(descriptor.rights_policy_version), attribution=descriptor.attribution,
        budget_json=budget.dump(), usage_json={}, status="pending", examined_count=0, staged_count=0,
        rejected_count=0, displayed_count=0, truncated=False, idempotency_key=idempotency_key, request_digest=digest,
        version=1, created_at=now, updated_at=now,
    )  # fmt: skip
    db.add(run)
    try:
        db.flush()
        receipt = job_service.enqueue_job(
            db, organization_id=org, environment=settings.environment, job_type=JOB_TYPE, schema_version=JOB_VERSION,
            payload={"run_id": str(run.id)}, idempotency_key=f"run.{run.id}", clock=clock,
        )  # fmt: skip
        run.job_id = receipt.job_id
        management._audit(db, actor, clock, "discovery.run_requested", run.id,
                          {"provider": provider, "budget": budget.dump(), "job_id": str(receipt.job_id)},
                          target_type="discovery_run")  # fmt: skip
        db.commit()
    except IntegrityError:
        db.rollback()  # a concurrent identical request committed first
        prior = replay()
        if prior is None:
            raise Conflict("concurrent run request did not commit; retry") from None
        return prior, False
    return run, True


def cancel_run(db: Session, *, actor: Actor, clock: Clock, run_id: uuid.UUID) -> DiscoveryRun:
    """Cooperative and idempotent. A pending run is cancelled now; a running one stops at its next check."""
    account_service._require(actor, Capability.MUTATE)
    run = _lock_run(db, actor.organization_id, run_id)
    if run is None:
        raise NotFound()
    if run.status in RUN_TERMINAL:
        db.rollback()
        return run
    now = clock.now()
    run.requested_cancel_at = run.requested_cancel_at or now
    if run.status == "pending":
        run.status, run.finished_at, run.partial_reason = "cancelled", now, "cancelled_before_start"
        db.execute(
            text(
                "UPDATE jobs SET status = 'cancelled', finished_at = :now, updated_at = :now"
                " WHERE organization_id = :org AND id = :job AND status IN ('pending', 'retry_wait')"
            ),
            {"now": now, "org": actor.organization_id, "job": run.job_id},
        )
    elif job_service.worker_gone(db, actor.organization_id, run.job_id):  # orphaned: no worker will finish it
        run.status, run.finished_at, run.partial_reason = "cancelled", now, "worker_lost"
    run.version += 1
    run.updated_at = now
    management._audit(db, actor, clock, "discovery.run_cancel_requested", run.id, {"status": run.status},
                      target_type="discovery_run")  # fmt: skip
    db.commit()
    return run


# --- worker -------------------------------------------------------------------------------------------------


def _finish(run: DiscoveryRun, status: str, now: datetime, **fields: Any) -> dict[str, Any]:
    run.status, run.finished_at, run.updated_at = status, now, now
    run.version += 1
    for name, value in fields.items():
        setattr(run, name, value)
    return {"run_id": str(run.id), "run_status": status}


def handle_run_job(
    db: Session, ctx: job_registry.JobContext, payload: job_registry.DiscoveryRunPayload
) -> dict[str, Any]:
    """At-least-once safe: terminal runs are never resurrected; staging and links are idempotent.

    The terminal state is written in the job's final transaction, which the P1.5 runner commits only with
    a fenced completion, so a worker whose lease was lost cannot write it.
    """
    if ctx.environment is None:
        raise job_registry.PermanentJobError("environment_unknown")
    run = _lock_run(db, ctx.organization_id, payload.run_id)
    if run is None:
        raise job_registry.PermanentJobError("run_not_found")
    if run.status in RUN_TERMINAL:
        return {"run_id": str(run.id), "run_status": run.status, "skipped": True}
    if run.requested_cancel_at is not None:
        return _finish(run, "cancelled", ctx.now, partial_reason="cancelled_before_start")
    run.status, run.started_at, run.updated_at = "running", run.started_at or ctx.now, ctx.now
    run.version += 1
    db.commit()  # progress is visible from durable state
    try:
        return _execute(db, ctx, payload.run_id)
    except job_registry.PermanentJobError:
        raise
    except Exception:
        if ctx.attempt < ctx.max_attempts:
            raise  # retried by P1.5 with backoff
        db.rollback()
        run = _lock_run(db, ctx.organization_id, payload.run_id)
        if run is None or run.status != "running":
            return {"run_id": str(payload.run_id), "skipped": True}
        return _finish(run, "failed", ctx.now, error_code="worker_error")


def _execute(db: Session, ctx: job_registry.JobContext, run_id: uuid.UUID) -> dict[str, Any]:
    org, environment = ctx.organization_id, str(ctx.environment)
    run = db.get(DiscoveryRun, run_id)
    assert run is not None  # noqa: S101  # locked and committed above
    creator = db.scalar(select(User).where(User.organization_id == org, User.id == run.created_by))
    role = Role(creator.role) if creator is not None else None
    if creator is None or role is None or not creator.active or Capability.MUTATE not in ROLE_CAPABILITIES[role]:
        return _finish(_lock_or_fail(db, org, run_id), "failed", ctx.now, error_code="requester_not_permitted")
    actor = Actor(user_id=creator.id, organization_id=org, role=role, session_id=uuid.uuid4(), verifier="")
    clock = FixedClock(ctx.now)
    settings = SETTINGS()
    budget = run.budget_json
    query = SourceQuery(city=run.city, vertical_slug=run.vertical_slug)

    def should_continue() -> bool:  # called before every adapter call
        job_registry.keep_alive(ctx)
        requested = db.scalar(
            select(DiscoveryRun.requested_cancel_at).where(
                DiscoveryRun.organization_id == org, DiscoveryRun.id == run_id
            )
        )
        return requested is None

    if run.provider == seed_import.PROVIDER:
        return _execute_seed_review(db, ctx, run_id, actor, clock)
    try:
        adapter = build_adapter(run.provider, settings)
        report = run_discovery(
            db, actor=actor, clock=clock, environment=environment, adapter=adapter, query=query,
            budget=DiscoveryBudget(max_candidates=min(int(budget["max_candidates"]), 30),
                                   max_search_pages=int(budget["max_search_pages"]),
                                   max_fetches=int(budget["max_fetches"]),
                                   max_seconds=float(min(int(budget["max_seconds"]), MAX_RUN_SECONDS))),
            persist=True, should_continue=should_continue,
        )  # fmt: skip
    except registry.SourcePolicyError as exc:
        db.rollback()
        return _finish(_lock_or_fail(db, org, run_id), "failed", ctx.now, error_code=exc.reason[:80])

    keys = [p.external_key for p in report.candidates if p.source_record_id]
    rows: dict[str, uuid.UUID] = {
        key: ident
        for key, ident in db.execute(
            select(DiscoveryCandidate.external_key, DiscoveryCandidate.id).where(
                DiscoveryCandidate.organization_id == org,
                DiscoveryCandidate.provider == run.provider,
                DiscoveryCandidate.external_key.in_(keys),
            )
        )
    }
    for position, key in enumerate(k for k in keys if k in rows):
        if position >= 30:
            break  # hard display ceiling for one run
        db.execute(
            insert(DiscoveryRunCandidate)
            .values(
                id=uuid.uuid4(),
                organization_id=org,
                run_id=run_id,
                candidate_id=rows[key],
                position=position,
                display_status="pending",
                version=1,
                created_at=ctx.now,
            )  # fmt: skip
            .on_conflict_do_nothing(index_elements=["organization_id", "run_id", "candidate_id"])
        )
    db.commit()
    resolution = resolution_service.run_resolution(db, actor=actor, clock=clock)

    run = _lock_or_fail(db, org, run_id)
    if run.status != "running":
        return {"run_id": str(run_id), "run_status": run.status, "skipped": True}  # finalized elsewhere
    displayed = int(
        db.scalar(
            select(func.count())
            .select_from(DiscoveryRunCandidate)
            .where(DiscoveryRunCandidate.organization_id == org, DiscoveryRunCandidate.run_id == run_id)
        )
        or 0
    )
    cancelled = run.requested_cancel_at is not None or report.stop_reason == "cancelled"
    if cancelled:
        status = "cancelled"
    elif report.stop_reason in ("completed", "candidate_cap"):
        status = "completed"
    else:
        status = "partial"
    return _finish(
        run, status, ctx.now,
        examined_count=report.examined_count,
        staged_count=report.staged_new_count + report.staged_revised_count + report.staged_unchanged_count,
        rejected_count=report.rejected_count, displayed_count=min(displayed, 30), truncated=report.truncated,
        stop_reason=report.stop_reason, partial_reason=report.stop_reason if status != "completed" else None,
        usage_json={**report.budget_consumed, "identity_pairs_considered": resolution.pairs_considered,
                    "identity_suggestions_created": resolution.created,
                    "rejection_reasons": report.rejection_reasons},
    )  # fmt: skip


def _lock_or_fail(db: Session, org: uuid.UUID, run_id: uuid.UUID) -> DiscoveryRun:
    run = _lock_run(db, org, run_id)
    if run is None:
        raise job_registry.PermanentJobError("run_not_found")
    return run


# --- review -------------------------------------------------------------------------------------------------


@dataclass
class ReviewResult:
    run_candidate: DiscoveryRunCandidate
    account_id: uuid.UUID | None
    replayed: bool
    converged: bool
    decision_id: uuid.UUID


def _rights_refusal(db: Session, candidate: DiscoveryCandidate, now: datetime, environment: str) -> str | None:
    """Admission needs evidence that is still permitted at review time."""
    if candidate.expires_at is not None and candidate.expires_at <= now:
        return "candidate_rights_expired"
    if candidate.source_record_id is not None:
        source = db.scalar(
            select(SourceRecord).where(
                SourceRecord.organization_id == candidate.organization_id, SourceRecord.id == candidate.source_record_id
            )
        )
        if source is None or (source.expires_at is not None and source.expires_at <= now):
            return "source_rights_expired"
        try:
            policy.check_storage(source.provider, source.permitted_storage_class, None, source.external_key)
        except policy.RightsViolation:
            return "source_rights_not_permitted"
    if candidate.provider == registry.FIXTURE_PROVIDER:
        try:
            registry.check_descriptor(registry.DESCRIPTORS[registry.FIXTURE_PROVIDER], environment, now=now)
        except registry.SourcePolicyError as exc:
            return exc.reason
    if candidate.provider == seed_import.PROVIDER:
        try:
            registry.check_descriptor(seed_import.DESCRIPTOR, environment, now=now)
        except registry.SourcePolicyError as exc:
            return exc.reason
    if candidate.provider == osm.PROVIDER:  # the owner may have disabled OSM or its rights review may have lapsed
        try:
            registry.check_descriptor(osm.descriptor_from_settings(SETTINGS()), environment, now=now)
        except registry.SourcePolicyError as exc:
            return exc.reason
    return None


def _confirmed_twin(db: Session, org: uuid.UUID, candidate_id: uuid.UUID) -> tuple[uuid.UUID, uuid.UUID] | None:
    """(suggestion, account) when a reviewer confirmed this candidate is the same campus as another listing that is
    already admitted: admission then joins that account instead of creating a duplicate."""
    other = case(
        (IdentitySuggestion.left_candidate_id == candidate_id, IdentitySuggestion.right_candidate_id),
        else_=IdentitySuggestion.left_candidate_id,
    )
    row = db.execute(
        select(IdentitySuggestion.id, CandidateAccountLink.account_id)
        .join(
            CandidateAccountLink,
            and_(
                CandidateAccountLink.organization_id == org,
                CandidateAccountLink.candidate_id == other,
                CandidateAccountLink.unlinked_at.is_(None),
            ),
        )
        .where(
            IdentitySuggestion.organization_id == org,
            IdentitySuggestion.status == "confirmed",
            IdentitySuggestion.right_candidate_id.is_not(None),
            or_(
                IdentitySuggestion.left_candidate_id == candidate_id,
                IdentitySuggestion.right_candidate_id == candidate_id,
            ),
        )
        .limit(1)
    ).first()
    return (row[0], row[1]) if row is not None else None


def _open_match(db: Session, org: uuid.UUID, candidate_id: uuid.UUID) -> bool:
    """A pending same-campus suggestion must be decided (P2.3) before a new account is created."""
    return (
        db.scalar(
            select(IdentitySuggestion.id)
            .where(
                IdentitySuggestion.organization_id == org,
                IdentitySuggestion.resolution == "suggest_review",
                IdentitySuggestion.status.in_(("pending", "deferred", "undone")),
                or_(
                    IdentitySuggestion.left_candidate_id == candidate_id,
                    IdentitySuggestion.right_candidate_id == candidate_id,
                ),
            )
            .limit(1)
        )  # fmt: skip
        is not None
    )


def _active_link(db: Session, org: uuid.UUID, candidate_id: uuid.UUID) -> CandidateAccountLink | None:
    return db.scalar(
        select(CandidateAccountLink).where(
            CandidateAccountLink.organization_id == org,
            CandidateAccountLink.candidate_id == candidate_id,
            CandidateAccountLink.unlinked_at.is_(None),
        )
    )


def review_candidate(
    db: Session, *, actor: Actor, clock: Clock, environment: str, run_id: uuid.UUID, candidate_id: uuid.UUID,
    action: ReviewAction, expected_version: int, idempotency_key: str, reason: str,
    existing_account_id: uuid.UUID | None = None,
) -> ReviewResult:  # fmt: skip
    account_service._require(actor, Capability.MUTATE)
    org = actor.organization_id
    try:
        reason = policy.clean_text(reason, "reason", 1000)
    except policy.PolicyViolation as exc:
        raise InvalidRequest(str(exc)) from None
    if len(reason) < 3:
        raise InvalidRequest("reason must be 3-1000 characters")
    if (action == "attach_existing") != (existing_account_id is not None):
        raise InvalidRequest("existing_account_id is required for attach_existing and only for it")
    digest = job_registry.digest(
        {"run": str(run_id), "candidate": str(candidate_id), "action": action, "version": expected_version,
         "reason": reason, "account": str(existing_account_id) if existing_account_id else None}
    )  # fmt: skip

    def replay() -> ReviewResult | None:
        prior = db.scalar(
            select(DiscoveryReviewDecision).where(
                DiscoveryReviewDecision.organization_id == org,
                DiscoveryReviewDecision.idempotency_key == idempotency_key,
            )
        )
        if prior is None:
            return None
        if prior.payload_digest != digest:
            raise Conflict("idempotency_key was already used with a different decision")
        row = db.scalar(
            select(DiscoveryRunCandidate).where(
                DiscoveryRunCandidate.organization_id == org,
                DiscoveryRunCandidate.run_id == prior.run_id,
                DiscoveryRunCandidate.candidate_id == prior.candidate_id,
            )
        )
        assert row is not None  # noqa: S101  # FK-backed
        return ReviewResult(row, prior.account_id, True, prior.converged, prior.id)

    prior = replay()
    if prior is not None:
        return prior
    row = db.scalar(
        select(DiscoveryRunCandidate)
        .where(
            DiscoveryRunCandidate.organization_id == org,
            DiscoveryRunCandidate.run_id == run_id,
            DiscoveryRunCandidate.candidate_id == candidate_id,
        )
        .with_for_update()
    )
    if row is None:
        raise NotFound()
    candidate = db.scalar(
        select(DiscoveryCandidate)
        .where(DiscoveryCandidate.organization_id == org, DiscoveryCandidate.id == candidate_id)
        .with_for_update()  # serializes admissions of one candidate across runs and reviewers
    )
    assert candidate is not None  # noqa: S101  # FK-backed
    prior = replay()  # an identical command may have committed while we waited for the lock
    if prior is not None:
        return prior
    now = clock.now()
    link = _active_link(db, org, candidate_id)
    converged = False
    account_id: uuid.UUID | None = None
    if (
        action == "accept_new"
        and link is not None
        and (row.display_status in ("pending", "deferred") or row.account_id == link.account_id)
    ):
        converged, account_id = True, link.account_id  # another reviewer already admitted this campus
        next_status = "accepted"
    else:
        if row.version != expected_version:
            raise Conflict("this candidate changed since you loaded it; reload and decide again")
        if REVIEW_TRANSITIONS[action].get(row.display_status) is None:
            raise Conflict(f"cannot {action} a candidate that is {row.display_status}")
        next_status = REVIEW_TRANSITIONS[action][row.display_status]
    if action in ("accept_new", "attach_existing"):  # also when converging: never mark expired evidence admitted
        refusal = _rights_refusal(db, candidate, now, environment)
        if refusal is not None:
            raise Conflict(f"cannot admit: {refusal}; a new permitted observation is required")
    if action == "accept_new" and not converged:
        twin = _confirmed_twin(db, org, candidate_id)
        if twin is not None:  # the same campus is already admitted: associate, never duplicate
            suggestion_id, account_id = twin
            db.add(
                CandidateAccountLink(
                    organization_id=org, candidate_id=candidate_id, account_id=account_id,
                    suggestion_id=suggestion_id, linked_by=actor.user_id, linked_at=now,
                )
            )  # fmt: skip
            candidate.status, candidate.updated_at = "admitted", now
        elif _open_match(db, org, candidate_id):
            raise Conflict("decide the possible same-campus match first (confirm or mark distinct)")
        else:
            account_id = _admit_new(db, actor, clock, candidate, run_id)
    elif action == "attach_existing":
        target = db.scalar(select(Account.id).where(Account.organization_id == org, Account.id == existing_account_id))
        if target is None:
            raise NotFound()
        if link is None or link.account_id != target:
            raise Conflict("confirm this candidate and account as the same campus first (identity review)")
        account_id = target
        candidate.status, candidate.updated_at = "admitted", now
    elif action == "reject":
        if link is not None:
            raise Conflict("this candidate is linked to an account; undo the link in identity review first")
        candidate.status, candidate.updated_at = "rejected", now

    prior_status = row.display_status
    row.display_status, row.account_id = next_status, account_id if next_status == "accepted" else row.account_id
    row.review_note, row.reviewed_by, row.reviewed_at = reason, actor.user_id, now
    row.version += 1
    decision = DiscoveryReviewDecision(
        organization_id=org, run_id=run_id, candidate_id=candidate_id, idempotency_key=idempotency_key, action=action,
        payload_digest=digest, prior_status=prior_status, next_status=next_status, account_id=account_id,
        converged=converged, actor_user_id=actor.user_id, reason=reason, request_id=current_request_id(),
        recorded_at=now,
    )  # fmt: skip
    db.add(decision)
    management._audit(db, actor, clock, "discovery.candidate_reviewed", candidate_id,
                      {"run_id": str(run_id), "action": action, "next_status": next_status, "converged": converged,
                       "account_id": str(account_id) if account_id else None},
                      target_type="discovery_candidate")  # fmt: skip
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        prior = replay()
        if prior is not None:
            return prior
        raise Conflict("this candidate changed since you loaded it; reload and decide again") from None
    return ReviewResult(row, account_id, False, converged, decision.id)


def _execute_seed_review(
    db: Session, ctx: job_registry.JobContext, run_id: uuid.UUID, actor: Actor, clock: Clock
) -> dict[str, Any]:
    """A review run over rows an operator CSV import already staged: nothing is fetched or re-staged.

    Rows go through the same identity matching, rights checks and reviewer decisions as any other run.
    """
    org = ctx.organization_id
    run = db.get(DiscoveryRun, run_id)
    assert run is not None  # noqa: S101
    limit = min(int(run.budget_json["max_candidates"]), 30)
    staged = list(
        db.scalars(
            select(DiscoveryCandidate.id)
            .where(
                DiscoveryCandidate.organization_id == org,
                DiscoveryCandidate.provider == seed_import.PROVIDER,
                DiscoveryCandidate.source_import_id == uuid.UUID(run.budget_json["seed_import_id"]),
                DiscoveryCandidate.status.not_in(("admitted", "rejected")),
            )
            .order_by(DiscoveryCandidate.created_at, DiscoveryCandidate.id)
            .limit(limit + 1)
        )
    )
    for position, candidate_id in enumerate(staged[:limit]):
        db.execute(
            insert(DiscoveryRunCandidate)
            .values(id=uuid.uuid4(), organization_id=org, run_id=run_id, candidate_id=candidate_id,
                    position=position, display_status="pending", version=1, created_at=ctx.now)
            .on_conflict_do_nothing(index_elements=["organization_id", "run_id", "candidate_id"])
        )  # fmt: skip
    db.commit()
    resolution = resolution_service.run_resolution(db, actor=actor, clock=clock)
    run = _lock_or_fail(db, org, run_id)
    if run.status != "running":
        return {"run_id": str(run_id), "run_status": run.status, "skipped": True}
    shown = min(len(staged), limit)
    truncated = len(staged) > limit
    return _finish(
        run, "completed", ctx.now, examined_count=shown, staged_count=0, rejected_count=0, displayed_count=shown,
        truncated=truncated, stop_reason="candidate_cap" if truncated else "completed",
        usage_json={"identity_pairs_considered": resolution.pairs_considered,
                    "identity_suggestions_created": resolution.created},
    )  # fmt: skip


def seed_imports(db: Session, org: uuid.UUID) -> list[SourceImport]:
    return list(
        db.scalars(
            select(SourceImport)
            .where(SourceImport.organization_id == org, SourceImport.provider == seed_import.PROVIDER)
            .order_by(SourceImport.imported_at.desc())
            .limit(50)
        )
    )


def _admit_new(db: Session, actor: Actor, clock: Clock, candidate: DiscoveryCandidate, run_id: uuid.UUID) -> uuid.UUID:
    """One P1.4 account (research pending), linked to its candidate and provenance. Nothing is inferred."""
    vertical = db.scalar(select(Vertical.id).where(Vertical.slug == VERTICAL))
    if vertical is None:
        raise NotFound()
    account = account_service.create_account(
        db, actor=actor, clock=clock, vertical_id=vertical, name=candidate.display_name, city=candidate.city,
        locality=candidate.locality, commit=False,
    )  # fmt: skip
    db.flush()
    now = clock.now()
    names = {policy.normalize_name(candidate.display_name)}
    if candidate.name_local:
        names.add(policy.normalize_name(candidate.name_local))  # the Urdu spelling stays as an alias
    names.discard(account.normalized_name)
    for name in sorted(n for n in names if n):
        db.add(AccountAlias(organization_id=actor.organization_id, account_id=account.id, normalized_name=name[:250],
                            source_record_id=candidate.source_record_id, created_at=now))  # fmt: skip
    db.add(CandidateAccountLink(organization_id=actor.organization_id, candidate_id=candidate.id, account_id=account.id,
                                suggestion_id=None, linked_by=actor.user_id, linked_at=now))  # fmt: skip
    candidate.status, candidate.updated_at = "admitted", now
    management._audit(db, actor, clock, "account.created", account.id,
                      {"version": 1, "origin": "discovery_review", "run_id": str(run_id),
                       "candidate_id": str(candidate.id), "provider": candidate.provider,
                       "source_record_id": str(candidate.source_record_id or "") or None})  # fmt: skip
    return account.id


# --- read models --------------------------------------------------------------------------------------------


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def run_view(db: Session, run: DiscoveryRun) -> dict[str, Any]:
    counts: dict[str, int] = {
        status: int(n)
        for status, n in db.execute(
            select(DiscoveryRunCandidate.display_status, func.count())
            .where(DiscoveryRunCandidate.organization_id == run.organization_id, DiscoveryRunCandidate.run_id == run.id)
            .group_by(DiscoveryRunCandidate.display_status)
        )
    }
    job_status = db.scalar(text("SELECT status FROM jobs WHERE organization_id = :org AND id = :id"),
                           {"org": run.organization_id, "id": run.job_id}) if run.job_id else None  # fmt: skip
    return {
        "id": str(run.id), "status": run.status, "version": run.version, "provider": run.provider,
        "synthetic": run.provider == registry.FIXTURE_PROVIDER, "area_label": run.area_label, "city": run.city,
        "vertical_slug": run.vertical_slug, "adapter_version": run.adapter_version,
        "rights_policy_version": run.rights_policy_version, "attribution": run.attribution, "budget": run.budget_json,
        "usage": run.usage_json, "examined_count": run.examined_count, "staged_count": run.staged_count,
        "rejected_count": run.rejected_count, "displayed_count": run.displayed_count, "truncated": run.truncated,
        "stop_reason": run.stop_reason, "partial_reason": run.partial_reason, "error_code": run.error_code,
        "review_counts": {s: int(counts.get(s, 0)) for s in ("pending", "accepted", "rejected", "deferred")},
        "job_id": str(run.job_id) if run.job_id else None, "job_status": job_status,
        "cancel_requested": run.requested_cancel_at is not None, "created_by": str(run.created_by),
        "created_at": _iso(run.created_at), "started_at": _iso(run.started_at), "finished_at": _iso(run.finished_at),
        "exhaustive": False,  # a bounded run is never a complete list of Lahore schools
    }  # fmt: skip


def run_candidates_view(db: Session, run: DiscoveryRun, now: datetime) -> list[dict[str, Any]]:
    org = run.organization_id
    rows = db.execute(
        select(DiscoveryRunCandidate, DiscoveryCandidate, SourceRecord.source_url)
        .join(DiscoveryCandidate, and_(DiscoveryCandidate.organization_id == org,
                                       DiscoveryCandidate.id == DiscoveryRunCandidate.candidate_id))
        .outerjoin(SourceRecord, and_(SourceRecord.organization_id == org,
                                      SourceRecord.id == DiscoveryCandidate.source_record_id))
        .where(DiscoveryRunCandidate.organization_id == org, DiscoveryRunCandidate.run_id == run.id)
        .order_by(DiscoveryRunCandidate.position)
        .limit(30)
    ).all()  # fmt: skip
    ids = [c.id for _, c, _ in rows]
    suggestions = list(
        db.scalars(
            select(IdentitySuggestion).where(
                IdentitySuggestion.organization_id == org,
                or_(IdentitySuggestion.left_candidate_id.in_(ids), IdentitySuggestion.right_candidate_id.in_(ids)),
            )
        )
    ) if ids else []  # fmt: skip
    counterpart_ids = {s.left_candidate_id for s in suggestions} | {s.right_candidate_id for s in suggestions
                                                                    if s.right_candidate_id}  # fmt: skip
    names: dict[uuid.UUID, str] = {
        ident: name
        for ident, name in db.execute(
            select(DiscoveryCandidate.id, DiscoveryCandidate.display_name).where(
                DiscoveryCandidate.organization_id == org, DiscoveryCandidate.id.in_(counterpart_ids)
            )
        )
    }
    account_ids = {s.existing_account_id for s in suggestions if s.existing_account_id}
    accounts: dict[uuid.UUID, str] = {
        ident: name
        for ident, name in db.execute(
            select(Account.id, Account.canonical_name).where(
                Account.organization_id == org, Account.id.in_(account_ids)
            )
        )
    }
    links = {
        link.candidate_id: link.account_id
        for link in db.scalars(select(CandidateAccountLink).where(
            CandidateAccountLink.organization_id == org, CandidateAccountLink.candidate_id.in_(ids),
            CandidateAccountLink.unlinked_at.is_(None)))
    } if ids else {}  # fmt: skip

    out = []
    for review, candidate, url in rows:
        matches = []
        for s in suggestions:
            if candidate.id not in (s.left_candidate_id, s.right_candidate_id):
                continue
            other_id: uuid.UUID = s.existing_account_id or (
                s.right_candidate_id if s.left_candidate_id == candidate.id and s.right_candidate_id
                else s.left_candidate_id
            )  # fmt: skip
            matches.append({
                "suggestion_id": str(s.id), "status": s.status, "version": s.version, "resolution": s.resolution,
                "reason_codes": s.reason_codes, "features": s.features,
                "counterpart_kind": "account" if s.existing_account_id else "candidate",
                "counterpart_id": str(other_id),
                "counterpart_name": accounts.get(other_id) if s.existing_account_id else names.get(other_id),
            })  # fmt: skip
        out.append({
            "candidate_id": str(candidate.id), "review_status": review.display_status, "version": review.version,
            "account_id": str(review.account_id) if review.account_id else None,
            "linked_account_id": str(links[candidate.id]) if candidate.id in links else None,
            "review_note": review.review_note, "reviewed_at": _iso(review.reviewed_at),
            "provider": candidate.provider, "external_key": candidate.external_key,
            "display_name": candidate.display_name, "name_local": candidate.name_local, "city": candidate.city,
            "locality": candidate.locality, "location_precision": candidate.location_precision,
            "latitude": float(candidate.latitude) if candidate.latitude is not None else None,
            "longitude": float(candidate.longitude) if candidate.longitude is not None else None,
            "source_url": url, "observed_at": _iso(candidate.observed_at),
            "upstream_timestamp": _iso(candidate.upstream_timestamp),
            "rights_policy_version": candidate.rights_policy_version, "attribution": candidate.attribution,
            "expires_at": _iso(candidate.expires_at),
            "expired": candidate.expires_at is not None and candidate.expires_at <= now,
            "candidate_status": candidate.status, "verification": "unverified",
            "unknowns": ["ownership", "campus_count", "decision_authority", "software", "contactability", "need"],
            "matches": matches,
        })  # fmt: skip
    return out


def list_runs(db: Session, org: uuid.UUID, limit: int, cursor: tuple[datetime, uuid.UUID] | None) -> list[DiscoveryRun]:
    query = (
        select(DiscoveryRun)
        .where(DiscoveryRun.organization_id == org)
        .order_by(DiscoveryRun.created_at.desc(), DiscoveryRun.id.desc())
        .limit(limit + 1)
    )
    if cursor is not None:
        created, ident = cursor
        query = query.where(
            or_(DiscoveryRun.created_at < created, and_(DiscoveryRun.created_at == created, DiscoveryRun.id < ident))
        )
    return list(db.scalars(query))


def get_run(db: Session, org: uuid.UUID, run_id: uuid.UUID) -> DiscoveryRun:
    run = db.scalar(select(DiscoveryRun).where(DiscoveryRun.organization_id == org, DiscoveryRun.id == run_id))
    if run is None:
        raise NotFound()
    return run
