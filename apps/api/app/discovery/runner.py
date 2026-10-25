"""Bounded, rights-aware discovery run over a registered adapter (P2.1, extended in P2.2).

Order of guarantees: policy is checked before the adapter is called; budgets
are fixed before the first call and can only be lowered; every record is
validated individually; only rights-permitted provenance is persisted, via
the P1.2 source service; nothing creates, merges or contacts accounts.
P2.2: policy is re-checked before every adapter call (a provider disabled
mid-run stops it), Retry-After/backoff waits come out of the time budget,
and persisted listings are staged as unreviewed candidates.
"""

import logging
import time
import uuid
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.accounts import management, policy
from app.accounts import service as source_service
from app.accounts.models import SourceRecord
from app.auth.dependencies import Capability
from app.auth.service import Actor
from app.core.clock import Clock
from app.core.errors import AppError
from app.core.request_context import current_request_id
from app.discovery import registry
from app.discovery.contracts import (
    CONTRACT_VERSION,
    STORE_OPERATION,
    AdapterResponseTooLarge,
    AdapterTransientError,
    AdapterUpstreamError,
    Operation,
    SourceAdapter,
    SourceCandidate,
    SourceObservation,
    SourceQuery,
)
from app.discovery.staging import stage_candidate

logger = logging.getLogger("app.discovery")

SYNTHETIC_LABEL = "SYNTHETIC FIXTURE DATA: fictional records, not real Lahore businesses or leads"
LIVE_LABEL = "UNVERIFIED LISTINGS: third-party records, not verified schools, prospects or contacts"
COMPLETENESS_NOTE = "Bounded run: at most 30 listings from one configured query; never an exhaustive list."


@dataclass(frozen=True)
class DiscoveryBudget:
    """Initial ceilings (Batch 03 §P2.1.2). Lower is allowed; higher needs a policy change, not a flag."""

    max_candidates: int = 30
    max_search_pages: int = 5
    max_fetches: int = 20
    max_seconds: float = 60.0
    max_cost_units: int = 50
    max_retries: int = 2

    CEILINGS = {"max_candidates": 30, "max_search_pages": 5, "max_fetches": 20, "max_seconds": 60.0,
                "max_cost_units": 50, "max_retries": 2}  # fmt: skip

    def __post_init__(self) -> None:
        for name, ceiling in self.CEILINGS.items():
            value = getattr(self, name)
            if not 0 <= value <= ceiling:
                raise ValueError(f"{name} must be between 0 and {ceiling}")


StopReason = Literal[
    "completed", "candidate_cap", "page_cap", "fetch_cap", "time_cap", "cost_cap", "rate_limited", "timeout",
    "cursor_cycle", "provider_quota", "unavailable", "response_too_large", "upstream_error", "policy_revoked",
    "cancelled",
]  # fmt: skip


class CandidatePreview(BaseModel):
    """Rights-filtered, explicitly unverified view. Never a fact, never an account."""

    status: Literal["unverified"] = "unverified"
    provider: str
    external_key: str
    display_name: str
    city: str
    locality: str | None
    source_url: str | None
    storage_class: str
    observed_at: datetime
    expires_at: datetime | None
    claim_hints: list[str]  # derived/full rights only; untrusted text, displayed as data
    excerpt: str | None  # full rights only
    source_record_id: str | None
    name_local: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    location_precision: str | None = None  # 'area_center' is a representative point, not an address
    upstream_timestamp: datetime | None = None
    attribution: str | None = None


class DiscoveryFixtureReport(BaseModel):
    """Run report for any provider (name kept from P2.1 for compatibility)."""

    run_id: str
    correlation_id: str | None
    label: str = SYNTHETIC_LABEL
    completeness_note: str = COMPLETENESS_NOTE
    attribution: str | None = None
    contract_version: str = CONTRACT_VERSION
    provider: str
    adapter_version: str
    rights_policy_version: str
    query: dict[str, Any]
    stop_reason: StopReason
    examined_count: int
    accepted_count: int
    rejected_count: int
    persisted_count: int
    already_recorded_count: int
    budget_limits: dict[str, float]
    budget_consumed: dict[str, float]
    rejection_reasons: dict[str, int]
    candidates: list[CandidatePreview]
    truncated: bool = False  # the provider had more matches than this bounded run took
    partial: bool = False  # stopped early by a budget, error or policy change
    staged_new_count: int = 0
    staged_revised_count: int = 0
    staged_unchanged_count: int = 0


@dataclass
class _Run:
    budget: DiscoveryBudget
    started: float
    monotonic: Callable[[], float]
    environment: str
    clock: Clock
    sleep: Callable[[float], None]
    should_continue: Callable[[], bool] = lambda: True
    pages: int = 0
    fetches: int = 0
    cost: int = 0
    retries: int = 0
    examined: int = 0
    rejected: Counter[str] = field(default_factory=Counter)
    stop: StopReason | None = None
    truncated: bool = False

    def elapsed(self) -> float:
        return self.monotonic() - self.started

    def out_of_time(self) -> bool:
        return self.elapsed() >= self.budget.max_seconds

    def still_permitted(self, adapter: SourceAdapter) -> bool:
        """Re-check policy (and cancellation) before each adapter call; either halts new calls."""
        if not self.should_continue():
            self.rejected["cancel_requested"] += 1
            self.stop = "cancelled"
            return False
        try:
            registry.check_descriptor(adapter.descriptor, self.environment, now=self.clock.now())
        except registry.SourcePolicyError as exc:
            self.rejected[f"policy_{exc.reason}"] += 1
            self.stop = "policy_revoked"
            return False
        return True


def _validate_query(descriptor: Any, query: SourceQuery) -> None:
    if query.city not in descriptor.supported_cities or query.vertical_slug not in descriptor.supported_verticals:
        raise registry.SourcePolicyError("unsupported_query")


def _screen(descriptor: Any, url: str | None) -> str | None:
    if url is None:
        return None
    try:
        policy.screen_url(url, "fixture" if not descriptor.allow_http else "manual_entry")
    except policy.PolicyViolation:
        raise ValueError("unsafe_url") from None
    host = (url.split("://", 1)[1].split("/", 1)[0].split(":", 1)[0]).lower()
    if host not in descriptor.allowed_hostnames:
        raise ValueError("unapproved_host")
    return url


def _clean(candidate: SourceCandidate) -> SourceCandidate:
    """Untrusted text stays data: NFKC, trimmed, no control/bidi-override characters."""
    return candidate.model_copy(
        update={
            "display_name": policy.clean_text(candidate.display_name, "display_name", 250),
            "name_local": policy.clean_text(candidate.name_local, "name_local", 250) if candidate.name_local else None,
            "locality": policy.clean_text(candidate.locality, "locality", 160) if candidate.locality else None,
        }
    )


def _search(adapter: SourceAdapter, query: SourceQuery, run: _Run) -> list[SourceCandidate]:
    descriptor = adapter.descriptor
    accepted: list[SourceCandidate] = []
    seen_keys: set[str] = set()
    seen_cursors: set[str] = set()
    cursor: str | None = None
    cap = min(run.budget.max_candidates, descriptor.result_limit)
    while True:
        if cap - len(accepted) <= 0:  # checked first: a full result is a candidate cap, not a partial page cap
            run.stop = "candidate_cap"
            break
        if run.pages >= run.budget.max_search_pages:
            run.stop = "page_cap"
            break
        if run.pages + run.fetches >= descriptor.request_quota:
            run.stop = "provider_quota"
            break
        if run.out_of_time():
            run.stop = "time_cap"
            break
        if run.cost >= run.budget.max_cost_units:
            run.stop = "cost_cap"
            break
        limit = min(descriptor.page_size, cap - len(accepted))
        if not run.still_permitted(adapter):
            break
        run.pages += 1
        try:
            raw = adapter.search(query=query, limit=limit, cursor=cursor)
        except AdapterTransientError as exc:
            run.rejected[f"search_{exc.reason}"] += 1
            if run.retries >= run.budget.max_retries:
                run.stop = exc.reason  # type: ignore[assignment]
                break
            wait = max(exc.retry_after or 0.0, descriptor.retry_backoff_seconds * (2**run.retries))
            if run.elapsed() + wait >= run.budget.max_seconds:
                run.rejected["retry_wait_exceeds_time_budget"] += 1  # honour Retry-After: stop, never hammer
                run.stop = exc.reason  # type: ignore[assignment]
                break
            run.retries += 1  # a retry consumes a page call from the same budget
            if wait > 0:
                run.sleep(wait)
            continue
        except AdapterResponseTooLarge:
            run.rejected["response_too_large"] += 1
            run.stop = "response_too_large"
            break
        except AdapterUpstreamError as exc:
            run.rejected[f"upstream_{exc}"[:60]] += 1
            run.stop = "upstream_error"
            break
        if not isinstance(raw, dict) or not isinstance(raw.get("candidates"), list):
            run.rejected["malformed_page"] += 1
            run.stop = "completed"
            break
        run.cost += int(raw.get("reported_cost_units") or 0) if isinstance(raw.get("reported_cost_units"), int) else 1
        records = raw["candidates"]
        if raw.get("truncated") is True:
            run.truncated = True
        if len(records) > limit:  # contract violation: truncate deterministically and count it
            run.rejected["page_oversized"] += len(records) - limit
            records = records[:limit]
        for record in records:
            run.examined += 1
            try:
                candidate = SourceCandidate.model_validate(record)
            except ValidationError:
                run.rejected["invalid_record"] += 1
                continue
            try:
                candidate = _clean(candidate)
            except policy.PolicyViolation:
                run.rejected["unsafe_text"] += 1
                continue
            if candidate.external_key is None:
                run.rejected["missing_key"] += 1
                continue
            if candidate.provider != descriptor.provider:
                run.rejected["provider_mismatch"] += 1
                continue
            if candidate.city != query.city or candidate.vertical_slug != query.vertical_slug:
                run.rejected["query_mismatch"] += 1
                continue
            if candidate.external_key in seen_keys:
                run.rejected["duplicate_key"] += 1
                continue
            try:
                _screen(descriptor, candidate.source_url)
            except ValueError as exc:
                run.rejected[str(exc)] += 1
                continue
            seen_keys.add(candidate.external_key)
            accepted.append(candidate)
            if len(accepted) >= cap:
                break
        next_cursor = raw.get("next_cursor")
        if not next_cursor:
            run.stop = "completed" if len(accepted) < cap else "candidate_cap"
            break
        if not isinstance(next_cursor, str) or len(next_cursor) > 512:
            run.rejected["malformed_cursor"] += 1
            run.stop = "completed"
            break
        if next_cursor in seen_cursors or next_cursor == cursor:
            run.rejected["cursor_cycle"] += 1
            run.stop = "cursor_cycle"
            break
        seen_cursors.add(next_cursor)
        cursor = next_cursor
    return accepted


def _observe(
    adapter: SourceAdapter, candidate: SourceCandidate, run: _Run, now: datetime
) -> tuple[SourceObservation | None, str | None]:
    """Returns (observation, None) or (None, rejection_code)."""
    descriptor = adapter.descriptor
    remote = not descriptor.fetch_from_search_capture  # captured observations cost no remote call
    if remote and run.fetches >= run.budget.max_fetches:
        return None, "fetch_budget_exhausted"
    if run.out_of_time():
        return None, "time_budget_exhausted"
    if not run.still_permitted(adapter):
        return None, str(run.stop)
    run.fetches += int(remote)
    try:
        raw = adapter.fetch(source_key=str(candidate.external_key))
        observation = SourceObservation.model_validate(raw)
    except AdapterTransientError as exc:
        return None, f"fetch_{exc.reason}"
    except (ValidationError, KeyError):
        return None, "invalid_observation"
    if observation.external_key != candidate.external_key or observation.provider != descriptor.provider:
        return None, "observation_mismatch"
    if observation.rights_policy_version != descriptor.rights_policy_version:
        return None, "rights_version_mismatch"
    if not registry.storage_allowed(descriptor, observation.permitted_storage_class):
        return None, "rights_denied"
    if STORE_OPERATION[observation.permitted_storage_class] not in descriptor.permitted_operations:
        return None, "rights_denied"
    if observation.expires_at is not None and observation.expires_at <= now:
        return None, "expired_observation"
    try:
        _screen(descriptor, observation.source_url)
    except ValueError as exc:
        return None, str(exc)
    return observation, None


def _preview(
    candidate: SourceCandidate, observation: SourceObservation, expires_at: datetime | None, record_id: str | None
) -> CandidatePreview:
    storage = observation.permitted_storage_class
    excerpt = observation.data.get("excerpt") if storage == "full_allowed" else None
    return CandidatePreview(
        provider=candidate.provider,
        external_key=str(candidate.external_key),
        display_name=candidate.display_name,
        city=candidate.city,
        locality=candidate.locality,
        source_url=observation.source_url,
        storage_class=storage,
        observed_at=observation.observed_at,
        expires_at=expires_at,
        claim_hints=list(candidate.claim_hints) if storage in ("derived_only", "full_allowed") else [],
        excerpt=excerpt[:1000] if isinstance(excerpt, str) else None,
        source_record_id=record_id,
        name_local=candidate.name_local,
        latitude=candidate.latitude,
        longitude=candidate.longitude,
        location_precision=candidate.location_precision,
        upstream_timestamp=candidate.upstream_timestamp,
        attribution=candidate.attribution,
    )


def run_discovery(
    db: Session,
    *,
    actor: Actor,
    clock: Clock,
    environment: str,
    adapter: SourceAdapter,
    query: SourceQuery,
    budget: DiscoveryBudget | None = None,
    persist: bool = True,
    monotonic: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
    should_continue: Callable[[], bool] = lambda: True,
) -> DiscoveryFixtureReport:
    source_service._require(actor, Capability.MUTATE)
    descriptor = adapter.descriptor
    try:  # all before any adapter call
        registry.check_descriptor(descriptor, environment, now=clock.now())
        registry.require_operation(descriptor, Operation.SEARCH)
        registry.require_operation(descriptor, Operation.FETCH)
        _validate_query(descriptor, query)
    except registry.SourcePolicyError as exc:
        _record_refusal(db, actor, clock, descriptor.provider, exc.reason, persist)
        raise

    budget = budget or DiscoveryBudget()
    run = _Run(budget=budget, started=monotonic(), monotonic=monotonic, environment=environment, clock=clock,
               sleep=sleep, should_continue=should_continue)  # fmt: skip
    run_id = str(uuid.uuid4())
    now = clock.now()
    candidates = _search(adapter, query, run)

    previews: list[CandidatePreview] = []
    persisted = already = 0
    staged: Counter[str] = Counter()
    for candidate in candidates:
        if run.stop in ("policy_revoked", "cancelled"):
            run.rejected[run.stop] += 1  # halted: nothing further is stored after revocation or cancellation
            continue
        observation, rejection = _observe(adapter, candidate, run, now)
        if observation is None:
            run.rejected[rejection or "rejected"] += 1
            if rejection in ("fetch_budget_exhausted", "time_budget_exhausted") and run.stop == "completed":
                run.stop = "fetch_cap" if rejection == "fetch_budget_exhausted" else "time_cap"
            continue
        ttl_end = observation.observed_at + descriptor.retention_ttl
        expires_at = min(observation.expires_at, ttl_end) if observation.expires_at else ttl_end
        record_id: str | None = None
        source_url = observation.source_url
        if persist and source_url is None:
            # Provenance needs a real source URL; never invent one. Preview only, counted.
            run.rejected["not_persisted_missing_url"] += 1
        elif persist and source_url is not None:
            key = f"{descriptor.provider}:{candidate.external_key}"
            existing = db.scalar(
                select(SourceRecord).where(
                    SourceRecord.organization_id == actor.organization_id,
                    SourceRecord.provider == descriptor.provider,
                    SourceRecord.external_key == key,
                )
            )
            if existing is not None:
                already += 1
                record_id = str(existing.id)
                if observation.observed_at > existing.observed_at:  # a newer permitted observation renews rights
                    existing.observed_at, existing.expires_at = observation.observed_at, expires_at
                    existing.rights_policy_version = observation.rights_policy_version
            else:
                try:
                    with db.begin_nested():
                        record = source_service.add_source_record(
                            db,
                            actor=actor,
                            clock=clock,
                            provider=descriptor.provider,
                            source_url=source_url,
                            observed_at=observation.observed_at,
                            storage_class=observation.permitted_storage_class,
                            rights_policy_version=observation.rights_policy_version,
                            external_key=key,
                            expires_at=expires_at,
                            commit=False,
                        )
                    persisted += 1
                    record_id = str(record.id)
                except AppError:
                    run.rejected["provenance_refused"] += 1
                    continue
            staged[
                stage_candidate(
                    db,
                    actor=actor,
                    clock=clock,
                    candidate=candidate,
                    rights_policy_version=observation.rights_policy_version,
                    expires_at=expires_at,
                    source_record_id=uuid.UUID(record_id),
                )
            ] += 1
        previews.append(_preview(candidate, observation, expires_at, record_id))

    run.stop = run.stop or "completed"
    fixture = descriptor.source_kind == "fixture"
    report = DiscoveryFixtureReport(
        run_id=run_id,
        correlation_id=current_request_id(),
        label=SYNTHETIC_LABEL if fixture else LIVE_LABEL,
        attribution=descriptor.attribution,
        provider=descriptor.provider,
        adapter_version=descriptor.adapter_version,
        rights_policy_version=str(descriptor.rights_policy_version),
        query=query.model_dump(),
        stop_reason=run.stop,
        examined_count=run.examined,
        accepted_count=len(previews),
        rejected_count=sum(run.rejected.values()),
        persisted_count=persisted,
        already_recorded_count=already,
        budget_limits={k: float(getattr(budget, k)) for k in DiscoveryBudget.CEILINGS},
        budget_consumed={
            "search_pages": run.pages,
            "fetches": run.fetches,
            "cost_units": run.cost,
            "retries": run.retries,
            "seconds": round(run.elapsed(), 3),
        },
        rejection_reasons=dict(sorted(run.rejected.items())),
        candidates=previews,
        truncated=run.truncated or run.stop == "candidate_cap",
        partial=run.stop not in ("completed", "candidate_cap"),
        staged_new_count=staged["new"],
        staged_revised_count=staged["revised"],
        staged_unchanged_count=staged["unchanged"],
    )
    if persist:
        management._audit(
            db,
            actor,
            clock,
            "discovery.fixture_run" if fixture else "discovery.source_run",
            uuid.UUID(run_id),
            {
                "provider": descriptor.provider,
                "rights_policy_version": report.rights_policy_version,
                "stop_reason": report.stop_reason,
                "truncated": report.truncated,
                "accepted": report.accepted_count,
                "rejected": report.rejected_count,
                "persisted": persisted,
                "already_recorded": already,
                "staged_new": report.staged_new_count,
                "staged_revised": report.staged_revised_count,
                "budget_consumed": report.budget_consumed,
            },
            target_type="discovery_run",
        )
        db.commit()
    logger.info(
        "discovery.run_finished",
        extra={
            "context": {
                "reason": report.stop_reason,
                "count": report.accepted_count,
                "failed": report.rejected_count,
            }
        },
    )
    return report


def _record_refusal(db: Session, actor: Actor, clock: Clock, provider: str, reason: str, persist: bool) -> None:
    """Typed denied event: a log line always, and an audit row when the run would have persisted."""
    logger.warning("discovery.source_denied", extra={"context": {"reason": reason}})
    if persist:
        management._audit(
            db,
            actor,
            clock,
            "discovery.run_refused",
            uuid.uuid4(),
            {"provider": provider, "reason": reason},
            target_type="discovery_run",
        )
        db.commit()
