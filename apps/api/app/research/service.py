"""Source-backed account research runs and claim review (P3.1, ADR-016).

Flow: an operator selects ≤5 sources already associated with an account.
The run is committed atomically with a `research.run` v1 job. The worker:
1. re-checks each source's rights;
2. fetches its document by source key (never by URL);
3. validates and normalizes the document in memory;
4. extracts typed claims with exact locators, then independently verifies them;
5. stores proposals (excerpt text only for `full_allowed` sources).

A reviewer accepts or rejects each proposal; acceptance re-checks rights and
creates one P1.4 source-supported fact. Rendering re-checks rights again and
withholds excerpts whose rights have lapsed.
"""

import hashlib
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import and_, exists, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, aliased

from app.accounts import management, policy
from app.accounts import service as account_service
from app.accounts.models import Account, AccountAlias, AccountFact, AccountStatus, SourceRecord
from app.auth.dependencies import ROLE_CAPABILITIES, Capability
from app.auth.models import Role, User
from app.auth.service import Actor
from app.core.clock import Clock
from app.core.errors import Conflict, InvalidRequest, NotFound
from app.discovery import registry
from app.discovery.contracts import Operation
from app.discovery.models import DiscoveryCandidate
from app.jobs import registry as job_registry
from app.jobs import service as job_service
from app.research import documents, extract
from app.research.models import RESEARCH_TERMINAL, ResearchClaim, ResearchObservation, ResearchRun
from app.resolution.models import CandidateAccountLink

JOB_TYPE, JOB_VERSION = "research.run", 1
MAX_SOURCES = 5
SOURCE_SECONDS, JOB_SECONDS = 30.0, 60.0
FETCHER: documents.DocumentFetcher = documents.FixtureDocumentFetcher()  # tests replace this hook
MONOTONIC: Callable[[], float] = time.monotonic


class ResearchBudget(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    max_claims: int = Field(default=25, ge=1, le=25)
    max_chars: int = Field(default=documents.MAX_NORMALIZED_CHARS_PER_JOB, ge=1000, le=60_000)


# --- source eligibility -------------------------------------------------------------------------------


def associated_sources(db: Session, org: uuid.UUID, account_id: uuid.UUID) -> dict[uuid.UUID, str]:
    """Sources explicitly tied to this account, with how: admitted listing, alias provenance or fact source."""
    found: dict[uuid.UUID, str] = {}
    linked = db.execute(
        select(DiscoveryCandidate.source_record_id)
        .join(CandidateAccountLink, and_(CandidateAccountLink.organization_id == org,
                                         CandidateAccountLink.candidate_id == DiscoveryCandidate.id))
        .where(DiscoveryCandidate.organization_id == org, CandidateAccountLink.account_id == account_id,
               CandidateAccountLink.unlinked_at.is_(None), DiscoveryCandidate.source_record_id.is_not(None))
    )  # fmt: skip
    for (source_id,) in linked:
        if source_id is not None:
            found.setdefault(source_id, "admitted_listing")
    for (source_id,) in db.execute(
        select(AccountAlias.source_record_id).where(
            AccountAlias.organization_id == org, AccountAlias.account_id == account_id,
            AccountAlias.source_record_id.is_not(None),
        )
    ):  # fmt: skip
        if source_id is not None:
            found.setdefault(source_id, "alias_provenance")
    for (source_id,) in db.execute(
        select(AccountFact.source_record_id).where(
            AccountFact.organization_id == org, AccountFact.account_id == account_id,
            AccountFact.source_record_id.is_not(None),
        )
    ):  # fmt: skip
        if source_id is not None:
            found.setdefault(source_id, "fact_source")
    return found


def ineligibility(source: SourceRecord, environment: str, now: datetime) -> str | None:
    """Why this source may not be researched right now (None = eligible). Checked at schedule, run and review."""
    if source.expires_at is not None and source.expires_at <= now:
        return "source_rights_expired"
    try:
        policy.check_storage(source.provider, source.permitted_storage_class, None, source.external_key)
        policy.screen_url(source.source_url, source.provider)
    except (policy.RightsViolation, policy.PolicyViolation):
        return "source_rights_not_permitted"
    if source.permitted_storage_class == "metadata_only":
        return "metadata_only_no_content"
    descriptor = registry.DESCRIPTORS.get(source.provider)
    if descriptor is None:
        return "live_fetch_not_authorized"  # no reviewed fetch-capable provider (e.g. first-party websites)
    try:
        registry.check_descriptor(descriptor, environment, now=now)
        registry.require_operation(descriptor, Operation.FETCH)
    except registry.SourcePolicyError as exc:
        return exc.reason
    if source.rights_policy_version != descriptor.rights_policy_version:
        return "rights_version_mismatch"
    return None


# --- create / cancel -----------------------------------------------------------------------------------------


def _account(db: Session, org: uuid.UUID, account_id: uuid.UUID) -> Account:
    account = db.scalar(select(Account).where(Account.organization_id == org, Account.id == account_id))
    if account is None:
        raise NotFound()
    return account


def create_run(
    db: Session, *, actor: Actor, clock: Clock, environment: str, account_id: uuid.UUID,
    source_record_ids: list[uuid.UUID], idempotency_key: str, budget: ResearchBudget,
) -> tuple[ResearchRun, bool]:  # fmt: skip
    account_service._require(actor, Capability.MUTATE)
    org = actor.organization_id
    account = _account(db, org, account_id)
    ids = sorted({str(s) for s in source_record_ids})
    digest = job_registry.digest({"account": str(account_id), "sources": ids, "budget": budget.model_dump()})

    def replay() -> ResearchRun | None:
        prior = db.scalar(
            select(ResearchRun).where(
                ResearchRun.organization_id == org, ResearchRun.idempotency_key == idempotency_key
            )
        )
        if prior is not None and prior.request_digest != digest:
            raise Conflict("idempotency_key was already used for a different research request")
        return prior

    prior = replay()
    if prior is not None:
        return prior, False
    if account.status == AccountStatus.EXCLUDED:
        raise Conflict("archived accounts are not researched")
    if not 1 <= len(ids) <= MAX_SOURCES:
        raise InvalidRequest(f"select between 1 and {MAX_SOURCES} sources")
    now = clock.now()
    associated = associated_sources(db, org, account_id)
    for source_id in ids:
        sid = uuid.UUID(source_id)
        if sid not in associated:
            raise InvalidRequest("source_not_associated_with_account")
        source = db.scalar(select(SourceRecord).where(SourceRecord.organization_id == org, SourceRecord.id == sid))
        reason = ineligibility(source, environment, now) if source else "source_not_found"
        if reason is not None:
            raise InvalidRequest(f"source is not eligible: {reason}")
    run = ResearchRun(
        organization_id=org, account_id=account_id, requested_by=actor.user_id, source_record_ids=ids,
        extractor_version=extract.EXTRACTOR_VERSION, budget_json=budget.model_dump(), usage_json={}, status="pending",
        sources_processed=0, sources_failed=0, claims_proposed=0, claims_abstained=0, idempotency_key=idempotency_key,
        request_digest=digest, version=1, created_at=now, updated_at=now,
    )  # fmt: skip
    db.add(run)
    try:
        db.flush()
        receipt = job_service.enqueue_job(
            db, organization_id=org, environment=environment, job_type=JOB_TYPE, schema_version=JOB_VERSION,
            payload={"run_id": str(run.id)}, idempotency_key=f"research.{run.id}", clock=clock,
        )  # fmt: skip
        run.job_id = receipt.job_id
        management._audit(db, actor, clock, "research.run_requested", account_id,
                          {"run_id": str(run.id), "sources": len(ids), "job_id": str(receipt.job_id)})  # fmt: skip
        db.commit()
    except IntegrityError:
        db.rollback()
        prior = replay()
        if prior is None:
            raise Conflict("concurrent research request did not commit; retry") from None
        return prior, False
    return run, True


def _lock_run(db: Session, org: uuid.UUID, run_id: uuid.UUID) -> ResearchRun | None:
    return db.scalar(
        select(ResearchRun).where(ResearchRun.organization_id == org, ResearchRun.id == run_id).with_for_update()
    )


def cancel_run(db: Session, *, actor: Actor, clock: Clock, run_id: uuid.UUID) -> ResearchRun:
    account_service._require(actor, Capability.MUTATE)
    run = _lock_run(db, actor.organization_id, run_id)
    if run is None:
        raise NotFound()
    if run.status in RESEARCH_TERMINAL:
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
    run.version += 1
    run.updated_at = now
    management._audit(db, actor, clock, "research.run_cancel_requested", run.account_id,
                      {"run_id": str(run.id), "status": run.status})  # fmt: skip
    db.commit()
    return run


# --- worker --------------------------------------------------------------------------------------------------


def _finish(run: ResearchRun, status: str, now: datetime, **fields: Any) -> dict[str, Any]:
    run.status, run.finished_at, run.updated_at = status, now, now
    run.version += 1
    for name, value in fields.items():
        setattr(run, name, value)
    return {"run_id": str(run.id), "run_status": status}


def handle_research_job(db: Session, ctx: job_registry.JobContext, payload: Any) -> dict[str, Any]:
    if ctx.environment is None:
        raise job_registry.PermanentJobError("environment_unknown")
    org, run_id = ctx.organization_id, uuid.UUID(str(payload.run_id))
    run = _lock_run(db, org, run_id)
    if run is None:
        raise job_registry.PermanentJobError("run_not_found")
    if run.status in RESEARCH_TERMINAL:
        return {"run_id": str(run.id), "run_status": run.status, "skipped": True}
    if run.requested_cancel_at is not None:
        return _finish(run, "cancelled", ctx.now, partial_reason="cancelled_before_start")
    run.status, run.started_at, run.updated_at = "running", run.started_at or ctx.now, ctx.now
    run.version += 1
    db.commit()
    try:
        return _execute(db, ctx, run_id)
    except job_registry.PermanentJobError:
        raise
    except Exception:
        if ctx.attempt < ctx.max_attempts:
            raise
        db.rollback()
        run = _lock_run(db, org, run_id)
        if run is None or run.status != "running":
            return {"run_id": str(run_id), "skipped": True}
        return _finish(run, "failed", ctx.now, error_code="worker_error")


def _execute(db: Session, ctx: job_registry.JobContext, run_id: uuid.UUID) -> dict[str, Any]:
    org, environment, now = ctx.organization_id, str(ctx.environment), ctx.now
    run = db.get(ResearchRun, run_id)
    assert run is not None  # noqa: S101  # locked and committed above
    requester = db.scalar(select(User).where(User.organization_id == org, User.id == run.requested_by))
    role = Role(requester.role) if requester is not None else None
    if requester is None or role is None or not requester.active or Capability.MUTATE not in ROLE_CAPABILITIES[role]:
        return _finish(_lock_required(db, org, run_id), "failed", now, error_code="requester_not_permitted")
    budget = ResearchBudget.model_validate(run.budget_json)
    associated = associated_sources(db, org, run.account_id)
    started = MONOTONIC()
    chars_left = budget.max_chars
    claims_left = budget.max_claims
    failures: list[str] = []
    abstained: dict[str, int] = {}
    processed = 0
    stopped: str | None = None

    for source_id in run.source_record_ids:
        if db.scalar(select(ResearchRun.requested_cancel_at).where(ResearchRun.id == run_id)) is not None:
            stopped = "cancelled"
            break
        if MONOTONIC() - started >= JOB_SECONDS:
            stopped = "job_time_budget"
            break
        sid = uuid.UUID(source_id)
        source = db.scalar(select(SourceRecord).where(SourceRecord.organization_id == org, SourceRecord.id == sid))
        reason = "source_not_associated_with_account" if sid not in associated else None
        reason = reason or (ineligibility(source, environment, now) if source else "source_not_found")
        observation: dict[str, Any] = {
            "status": "skipped", "reason_code": reason, "content_sha256": None, "normalized_chars": 0,
            "truncated": False, "language": None, "retrieved_at": None,
        }  # fmt: skip
        doc: documents.NormalizedDocument | None = None
        if reason is None and source is not None:
            fetch_started = MONOTONIC()
            try:
                raw = FETCHER.fetch(provider=source.provider, source_key=str(source.external_key), now=now)
                if MONOTONIC() - fetch_started > SOURCE_SECONDS:
                    raise documents.DocumentError("source_time_budget")
                doc = documents.normalize(raw, chars_left)
            except documents.DocumentError as exc:
                observation |= {"status": "failed", "reason_code": exc.reason}
                failures.append(exc.reason)
            else:
                chars_left -= len(doc.text)
                observation |= {"status": "processed", "reason_code": None, "content_sha256": doc.sha256,
                                "normalized_chars": len(doc.text), "truncated": doc.truncated,
                                "language": doc.language, "retrieved_at": raw.retrieved_at}  # fmt: skip
        observation_id = _upsert_observation(db, org, run_id, sid, source, observation, now)
        if doc is not None and source is not None and observation_id is not None:
            result = extract.extract(doc.text, limit=claims_left)
            for key, value in result.abstained.items():
                abstained[key] = abstained.get(key, 0) + value
            for proposal in result.proposals:
                rejection = extract.verify(doc.text, proposal, proposal.span_sha256(doc.text))
                if rejection is not None:
                    abstained[f"verifier_{rejection}"] = abstained.get(f"verifier_{rejection}", 0) + 1
                    continue
                if _store_claim(db, org, run, observation_id, source, doc, proposal, now):
                    claims_left -= 1
            processed += 1
        db.commit()  # per-source progress is durable; rows are idempotent on (run, source) and span

    run = _lock_required(db, org, run_id)
    if run.status != "running":
        return {"run_id": str(run_id), "run_status": run.status, "skipped": True}
    proposed = int(db.scalar(text("SELECT count(*) FROM research_claims WHERE organization_id = :o AND run_id = :r"),
                             {"o": org, "r": run_id}) or 0)  # fmt: skip
    if stopped == "cancelled" or run.requested_cancel_at is not None:
        status, partial = "cancelled", "cancelled"
    elif stopped is not None:
        status, partial = "partial", stopped
    elif failures and processed == 0:
        status, partial = "failed", failures[0]
    elif failures:
        status, partial = "partial", failures[0]
    else:
        status, partial = "completed", None
    return _finish(
        run, status, now, sources_processed=processed, sources_failed=len(failures), claims_proposed=min(proposed, 25),
        claims_abstained=sum(abstained.values()), partial_reason=partial,
        error_code=failures[0] if status == "failed" else None,
        usage_json={"seconds": round(MONOTONIC() - started, 3), "chars": budget.max_chars - chars_left,
                    "abstained": dict(sorted(abstained.items())), "failures": failures},
    )  # fmt: skip


def _lock_required(db: Session, org: uuid.UUID, run_id: uuid.UUID) -> ResearchRun:
    run = _lock_run(db, org, run_id)
    if run is None:
        raise job_registry.PermanentJobError("run_not_found")
    return run


def _upsert_observation(
    db: Session, org: uuid.UUID, run_id: uuid.UUID, source_id: uuid.UUID, source: SourceRecord | None,
    fields: dict[str, Any], now: datetime,
) -> uuid.UUID | None:  # fmt: skip
    db.execute(
        insert(ResearchObservation)
        .values(id=uuid.uuid4(), organization_id=org, run_id=run_id, source_record_id=source_id,
                storage_class=source.permitted_storage_class if source else "metadata_only",
                rights_policy_version=source.rights_policy_version if source else "unknown", created_at=now, **fields)
        .on_conflict_do_nothing(constraint="uq_research_obs_run_source")
    )  # fmt: skip
    return db.scalar(
        select(ResearchObservation.id).where(
            ResearchObservation.organization_id == org, ResearchObservation.run_id == run_id,
            ResearchObservation.source_record_id == source_id, ResearchObservation.status == "processed",
        )
    )  # fmt: skip


def _store_claim(
    db: Session, org: uuid.UUID, run: ResearchRun, observation_id: uuid.UUID, source: SourceRecord,
    doc: documents.NormalizedDocument, proposal: extract.Proposal, now: datetime,
) -> bool:  # fmt: skip
    span = doc.text[proposal.start : proposal.end]
    excerpt = extract.redact_excerpt(span) if source.permitted_storage_class == "full_allowed" else None
    inserted = db.scalar(
        insert(ResearchClaim)
        .values(id=uuid.uuid4(), organization_id=org, run_id=run.id, account_id=run.account_id,
                observation_id=observation_id, source_record_id=source.id, claim_type=proposal.claim_type,
                typed_value_json=proposal.value, rule_id=proposal.rule_id, extractor_version=extract.EXTRACTOR_VERSION,
                storage_class=source.permitted_storage_class, language=doc.language, locator_start=proposal.start,
                locator_end=proposal.end, span_sha256=hashlib.sha256(span.encode("utf-8")).hexdigest(),
                excerpt=excerpt, status="proposed", version=1, created_at=now)
        .on_conflict_do_nothing(constraint="uq_research_claims_span")
        .returning(ResearchClaim.id)
    )  # fmt: skip
    return inserted is not None


# --- review -------------------------------------------------------------------------------------------------


@dataclass
class ReviewResult:
    claim: ResearchClaim
    fact_id: uuid.UUID | None
    replayed: bool


def review_claim(
    db: Session, *, actor: Actor, clock: Clock, environment: str, claim_id: uuid.UUID,
    action: Literal["accept", "reject"], expected_version: int, reason: str, idempotency_key: str,
    confidence_label: Literal["strong", "moderate", "weak"] = "moderate",
) -> ReviewResult:  # fmt: skip
    account_service._require(actor, Capability.MUTATE)
    org = actor.organization_id
    try:
        reason = policy.clean_text(reason, "reason", 1000)
    except policy.PolicyViolation as exc:
        raise InvalidRequest(str(exc)) from None
    if len(reason) < 3:
        raise InvalidRequest("reason must be 3-1000 characters")
    keyed = db.scalar(select(ResearchClaim).where(ResearchClaim.organization_id == org,
                                                  ResearchClaim.review_key == idempotency_key))  # fmt: skip
    if keyed is not None:
        same = keyed.id == claim_id and keyed.status == ("accepted" if action == "accept" else "rejected")
        if not same or keyed.review_reason != reason:
            raise Conflict("idempotency_key was already used with a different review")
        return ReviewResult(keyed, keyed.fact_id, True)
    claim = db.scalar(
        select(ResearchClaim)
        .where(ResearchClaim.organization_id == org, ResearchClaim.id == claim_id)
        .with_for_update()
    )
    if claim is None:
        raise NotFound()
    if claim.version != expected_version:
        raise Conflict("this claim changed since you loaded it; reload and review again")
    if claim.status != "proposed":
        raise Conflict(f"cannot review a claim that is {claim.status}")
    now = clock.now()
    fact_id: uuid.UUID | None = None
    if action == "accept":
        source = db.scalar(select(SourceRecord).where(SourceRecord.organization_id == org,
                                                      SourceRecord.id == claim.source_record_id))  # fmt: skip
        refusal = ineligibility(source, environment, now) if source else "source_not_found"
        if refusal is not None:
            raise Conflict(f"cannot accept: {refusal}")
        account = _account(db, org, claim.account_id)
        if account.status == AccountStatus.EXCLUDED:
            raise Conflict("archived accounts cannot gain facts")
        observation = db.get(ResearchObservation, claim.observation_id)
        observed_at = observation.retrieved_at if observation and observation.retrieved_at else now
        fact_id = _existing_fact(db, org, claim) or _new_fact(db, actor, clock, claim, confidence_label, observed_at)
    claim.status = "accepted" if action == "accept" else "rejected"
    claim.fact_id = fact_id
    claim.review_key, claim.review_reason, claim.reviewed_by, claim.reviewed_at = (
        idempotency_key,
        reason,
        actor.user_id,
        now,
    )
    claim.version += 1
    management._audit(db, actor, clock, "research.claim_reviewed", claim.account_id,
                      {"claim_id": str(claim.id), "action": action, "fact_id": str(fact_id) if fact_id else None,
                       "claim_type": claim.claim_type})  # fmt: skip
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise Conflict("this claim changed since you loaded it; reload and review again") from None
    return ReviewResult(claim, fact_id, False)


def _existing_fact(db: Session, org: uuid.UUID, claim: ResearchClaim) -> uuid.UUID | None:
    """Same claim, value and source already recorded as a current fact: link to it instead of duplicating."""
    successor = aliased(AccountFact)
    found: uuid.UUID | None = db.scalar(
        select(AccountFact.id).where(
            AccountFact.organization_id == org, AccountFact.account_id == claim.account_id,
            AccountFact.claim_type == claim.claim_type, AccountFact.typed_value_json == claim.typed_value_json,
            AccountFact.source_record_id == claim.source_record_id,
            AccountFact.verification_status == "source_supported",
            ~exists().where(successor.organization_id == org, successor.supersedes_fact_id == AccountFact.id),
        ).limit(1)
    )  # fmt: skip
    return found


def _new_fact(
    db: Session, actor: Actor, clock: Clock, claim: ResearchClaim, confidence: str, observed_at: datetime
) -> uuid.UUID:
    fact = account_service.add_account_fact(
        db, actor=actor, clock=clock, account_id=claim.account_id, claim_type=claim.claim_type,
        typed_value=claim.typed_value_json, confidence_label=confidence, verification_status="source_supported",
        observed_at=observed_at, source_record_id=claim.source_record_id, evidence_excerpt=claim.excerpt,
        recorded_by=actor.user_id, commit=False,
    )  # fmt: skip
    db.flush()
    management._audit(db, actor, clock, "account.fact_added", claim.account_id,
                      {"fact_id": str(fact.id), "claim_type": fact.claim_type, "origin": "research_review",
                       "research_claim_id": str(claim.id), "source_id": str(claim.source_record_id)})  # fmt: skip
    return fact.id


# --- read models --------------------------------------------------------------------------------------------


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def run_view(run: ResearchRun) -> dict[str, Any]:
    return {
        "id": str(run.id), "account_id": str(run.account_id), "status": run.status, "version": run.version,
        "source_record_ids": run.source_record_ids, "extractor_version": run.extractor_version,
        "budget": run.budget_json, "usage": run.usage_json, "sources_processed": run.sources_processed,
        "sources_failed": run.sources_failed, "claims_proposed": run.claims_proposed,
        "claims_abstained": run.claims_abstained, "partial_reason": run.partial_reason, "error_code": run.error_code,
        "cancel_requested": run.requested_cancel_at is not None, "created_at": _iso(run.created_at),
        "started_at": _iso(run.started_at), "finished_at": _iso(run.finished_at),
    }  # fmt: skip


def run_detail(db: Session, run: ResearchRun, environment: str, now: datetime) -> dict[str, Any]:
    org = run.organization_id
    sources = {
        s.id: s
        for s in db.scalars(select(SourceRecord).where(
            SourceRecord.organization_id == org, SourceRecord.id.in_([uuid.UUID(i) for i in run.source_record_ids])))
    }  # fmt: skip
    observations = list(db.scalars(select(ResearchObservation).where(
        ResearchObservation.organization_id == org, ResearchObservation.run_id == run.id)))  # fmt: skip
    claims = list(db.scalars(select(ResearchClaim).where(ResearchClaim.organization_id == org,
                                                         ResearchClaim.run_id == run.id)
                             .order_by(ResearchClaim.source_record_id, ResearchClaim.locator_start)))  # fmt: skip

    def source_view(source_id: uuid.UUID) -> dict[str, Any]:
        source = sources.get(source_id)
        if source is None:
            return {"id": str(source_id)}
        refusal = ineligibility(source, environment, now)
        url = source.source_url if refusal != "source_rights_not_permitted" else None
        return {"id": str(source.id), "provider": source.provider, "source_url": url,
                "storage_class": source.permitted_storage_class, "rights_policy_version": source.rights_policy_version,
                "observed_at": _iso(source.observed_at), "expires_at": _iso(source.expires_at),
                "current_rights": "ok" if refusal is None else refusal}  # fmt: skip

    def claim_view(claim: ResearchClaim) -> dict[str, Any]:
        source = sources.get(claim.source_record_id)
        refusal = ineligibility(source, environment, now) if source else "source_not_found"
        withheld = claim.excerpt is not None and refusal is not None
        return {
            "id": str(claim.id), "status": claim.status, "version": claim.version, "claim_type": claim.claim_type,
            "value": claim.typed_value_json, "rule_id": claim.rule_id, "extractor_version": claim.extractor_version,
            "language": claim.language, "locator": {"start": claim.locator_start, "end": claim.locator_end},
            "span_sha256": claim.span_sha256, "excerpt": None if withheld else claim.excerpt,
            "excerpt_withheld_reason": refusal if withheld else None,
            "excerpt_policy": "stored" if claim.excerpt is not None else "locator_only",
            "source": source_view(claim.source_record_id), "fact_id": str(claim.fact_id) if claim.fact_id else None,
            "review_reason": claim.review_reason, "reviewed_at": _iso(claim.reviewed_at),
            "verification": "accepted_by_reviewer" if claim.status == "accepted" else claim.status,
        }  # fmt: skip

    return run_view(run) | {
        "observations": [
            {"source": source_view(o.source_record_id), "status": o.status, "reason_code": o.reason_code,
             "language": o.language, "normalized_chars": o.normalized_chars, "truncated": o.truncated,
             "retrieved_at": _iso(o.retrieved_at)}
            for o in observations
        ],
        "claims": [claim_view(c) for c in claims],
    }  # fmt: skip


def sources_view(
    db: Session, org: uuid.UUID, account_id: uuid.UUID, environment: str, now: datetime
) -> list[dict[str, Any]]:
    associated = associated_sources(db, org, account_id)
    if not associated:
        return []
    rows = db.scalars(select(SourceRecord).where(SourceRecord.organization_id == org,
                                                 SourceRecord.id.in_(list(associated))))  # fmt: skip
    items = []
    for s in rows:
        refusal = ineligibility(s, environment, now)
        items.append({
            "id": str(s.id), "provider": s.provider, "source_url": s.source_url, "association": associated[s.id],
            "storage_class": s.permitted_storage_class, "rights_policy_version": s.rights_policy_version,
            "observed_at": _iso(s.observed_at), "expires_at": _iso(s.expires_at), "eligible": refusal is None,
            "ineligible_reason": refusal,
        })  # fmt: skip
    return sorted(items, key=lambda item: (not item["eligible"], item["provider"], item["id"]))


def get_run(db: Session, org: uuid.UUID, run_id: uuid.UUID) -> ResearchRun:
    run = db.scalar(select(ResearchRun).where(ResearchRun.organization_id == org, ResearchRun.id == run_id))
    if run is None:
        raise NotFound()
    return run
