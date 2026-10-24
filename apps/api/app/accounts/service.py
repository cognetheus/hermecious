"""Actor-scoped application services for accounts, sources and facts (P1.2).

The organization always comes from the authenticated `Actor`, never from
input. Lookups outside the actor's organization behave exactly like missing
rows (NotFound), so nothing leaks across organizations. Each mutation is one
transaction: on any failure nothing is persisted.
"""

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.accounts import claims, policy
from app.accounts.models import (
    Account,
    AccountAlias,
    AccountFact,
    AccountStatus,
    ConfidenceLabel,
    SourceRecord,
    VerificationStatus,
    Vertical,
)
from app.auth.dependencies import ROLE_CAPABILITIES, Capability
from app.auth.service import Actor
from app.core.clock import Clock
from app.core.errors import Conflict, Forbidden, InvalidRequest, NotFound

# New assertions start as one of these; disputed/rejected come from later review flows.
NEW_FACT_STATUSES = frozenset({VerificationStatus.SOURCE_SUPPORTED, VerificationStatus.HYPOTHESIS})
CLOCK_SKEW = timedelta(minutes=5)


def _require(actor: Actor, capability: Capability) -> None:
    if capability not in ROLE_CAPABILITIES[actor.role]:
        raise Forbidden()


def _aware(value: datetime, field: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise InvalidRequest(f"{field} must include a timezone offset")
    return value


def _commit(db: Session, conflict_message: str, commit: bool = True) -> None:
    """Commit (default) or just flush, so callers can compose one larger transaction."""
    try:
        if commit:
            db.commit()
        else:
            db.flush()
    except IntegrityError:
        db.rollback()
        raise Conflict(conflict_message) from None


def _policy(call: Any, *args: Any, **kwargs: Any) -> Any:
    try:
        return call(*args, **kwargs)
    except policy.RightsViolation as exc:
        raise Forbidden(str(exc)) from None
    except policy.PolicyViolation as exc:
        raise InvalidRequest(str(exc)) from None


def _account(db: Session, actor: Actor, account_id: uuid.UUID) -> Account:
    account = db.scalar(
        select(Account).where(Account.id == account_id, Account.organization_id == actor.organization_id)
    )
    if account is None:
        raise NotFound()
    return account


def _source(db: Session, actor: Actor, source_id: uuid.UUID) -> SourceRecord:
    source = db.scalar(
        select(SourceRecord).where(SourceRecord.id == source_id, SourceRecord.organization_id == actor.organization_id)
    )
    if source is None:
        raise NotFound()
    return source


def create_account(
    db: Session,
    *,
    actor: Actor,
    clock: Clock,
    vertical_id: uuid.UUID,
    name: str,
    city: str,
    locality: str | None = None,
    commit: bool = True,
) -> Account:
    _require(actor, Capability.MUTATE)
    canonical = _policy(policy.clean_text, name, "name", 250)
    vertical = db.get(Vertical, vertical_id)
    if vertical is None or vertical.status != "active":
        raise NotFound()
    now = clock.now()
    account = Account(
        organization_id=actor.organization_id,
        vertical_id=vertical.id,
        canonical_name=canonical,
        normalized_name=policy.normalize_name(canonical),
        city=_policy(policy.clean_text, city, "city", 120),
        locality=_policy(policy.clean_text, locality, "locality", 160) if locality else None,
        status=AccountStatus.DISCOVERED,
        discovered_at=now,
        updated_at=now,
    )
    db.add(account)
    _commit(db, "Account could not be created", commit)
    return account


def add_source_record(
    db: Session,
    *,
    actor: Actor,
    clock: Clock,
    provider: str,
    source_url: str,
    observed_at: datetime,
    storage_class: str,
    rights_policy_version: str,
    external_key: str | None = None,
    payload_reference: str | None = None,
    expires_at: datetime | None = None,
    commit: bool = True,
) -> SourceRecord:
    _require(actor, Capability.MUTATE)
    _policy(policy.check_storage, provider, storage_class, payload_reference, external_key)
    url = _policy(policy.screen_url, source_url, provider)
    now = clock.now()
    observed_at = _aware(observed_at, "observed_at")
    if observed_at > now + CLOCK_SKEW:
        raise InvalidRequest("observed_at is in the future")
    if expires_at is not None and _aware(expires_at, "expires_at") <= observed_at:
        raise InvalidRequest("expires_at must be after observed_at")
    record = SourceRecord(
        organization_id=actor.organization_id,
        provider=provider,
        external_key=_policy(policy.clean_text, external_key, "external_key", 300) if external_key else None,
        source_url=url,
        observed_at=observed_at,
        permitted_storage_class=storage_class,
        source_payload_reference=payload_reference,
        rights_policy_version=_policy(policy.clean_text, rights_policy_version, "rights_policy_version", 80),
        expires_at=expires_at,
        created_at=now,
    )
    db.add(record)
    _commit(db, "A source with this provider and external key already exists", commit)
    return record


def add_alias(
    db: Session,
    *,
    actor: Actor,
    clock: Clock,
    account_id: uuid.UUID,
    name: str,
    source_record_id: uuid.UUID | None = None,
) -> AccountAlias:
    _require(actor, Capability.MUTATE)
    account = _account(db, actor, account_id)
    if source_record_id is not None:
        _source(db, actor, source_record_id)
    normalized = policy.normalize_name(_policy(policy.clean_text, name, "alias", 250))
    if not normalized:
        raise InvalidRequest("alias must contain letters or digits")
    alias = AccountAlias(
        organization_id=actor.organization_id,
        account_id=account.id,
        normalized_name=normalized,
        source_record_id=source_record_id,
        created_at=clock.now(),
    )
    db.add(alias)
    _commit(db, "This alias already exists for the account")
    return alias


def add_account_fact(
    db: Session,
    *,
    actor: Actor,
    clock: Clock,
    account_id: uuid.UUID,
    claim_type: str,
    typed_value: dict[str, Any],
    confidence_label: str,
    verification_status: str,
    observed_at: datetime,
    source_record_id: uuid.UUID | None = None,
    expires_at: datetime | None = None,
    evidence_excerpt: str | None = None,
    recorded_by: uuid.UUID | None = None,
    supersedes_fact_id: uuid.UUID | None = None,
    correction_reason: str | None = None,
    commit: bool = True,
) -> AccountFact:
    _require(actor, Capability.MUTATE)
    account = _account(db, actor, account_id)
    claim = _policy(claims.parse_claim, claim_type, typed_value)
    try:
        status = VerificationStatus(verification_status)
        confidence = ConfidenceLabel(confidence_label)
    except ValueError:
        raise InvalidRequest("verification status or confidence label is invalid") from None
    if status not in NEW_FACT_STATUSES:
        raise InvalidRequest("new facts must be source_supported or hypothesis")
    now = clock.now()
    observed_at = _aware(observed_at, "observed_at")
    if observed_at > now + CLOCK_SKEW:
        raise InvalidRequest("observed_at is in the future")
    if expires_at is not None and _aware(expires_at, "expires_at") <= observed_at:
        raise InvalidRequest("expires_at must be after observed_at")

    source = _source(db, actor, source_record_id) if source_record_id is not None else None
    if claim.is_unknown and (status != VerificationStatus.HYPOTHESIS or confidence != ConfidenceLabel.UNKNOWN):
        raise InvalidRequest("an unknown value can only be a hypothesis with unknown confidence")
    if status == VerificationStatus.SOURCE_SUPPORTED:
        if source is None:
            raise InvalidRequest("a source-supported fact requires a source record")
        if confidence == ConfidenceLabel.UNKNOWN:
            raise InvalidRequest("a source-supported fact cannot have unknown confidence")
        if source.expires_at is not None and source.expires_at <= now:
            raise InvalidRequest("the source record has expired; re-verify before asserting new facts")
    if status == VerificationStatus.HYPOTHESIS and confidence == ConfidenceLabel.STRONG:
        raise InvalidRequest("a hypothesis cannot have strong confidence")
    excerpt = _policy(policy.check_excerpt, evidence_excerpt, source.permitted_storage_class if source else None)

    fact = AccountFact(
        organization_id=actor.organization_id,
        account_id=account.id,
        claim_type=claim_type,
        typed_value_json=claim.model_dump(mode="json"),
        confidence_label=confidence,
        verification_status=status,
        source_record_id=source.id if source else None,
        evidence_excerpt=excerpt,
        observed_at=observed_at,
        expires_at=expires_at,
        created_at=now,
        supersedes_fact_id=supersedes_fact_id,
        correction_reason=correction_reason,
        recorded_by=recorded_by,
    )
    db.add(fact)
    _commit(db, "This fact was already corrected; correct its latest version", commit)
    return fact


@dataclass(frozen=True)
class SourceView:
    id: uuid.UUID
    provider: str
    source_url: str
    permitted_storage_class: str
    rights_policy_version: str
    observed_at: datetime
    expires_at: datetime | None


@dataclass(frozen=True)
class FactView:
    id: uuid.UUID
    claim_type: str
    value: dict[str, Any]
    confidence_label: str
    verification_status: str
    observed_at: datetime
    evidence_excerpt: str | None
    source: SourceView | None
    # Stale when the fact or its source has passed its expiry: never present it as current.
    is_stale: bool
    expires_at: datetime | None = None
    created_at: datetime | None = None
    recorded_by: uuid.UUID | None = None
    # Correction chain: a fact with a successor is history, not the current assertion.
    supersedes_fact_id: uuid.UUID | None = None
    superseded_by_fact_id: uuid.UUID | None = None
    correction_reason: str | None = None

    @property
    def is_current(self) -> bool:
        return self.superseded_by_fact_id is None


@dataclass(frozen=True)
class AccountEvidence:
    account: Account
    aliases: list[str]
    facts: list[FactView]


def get_account_with_evidence(db: Session, *, actor: Actor, clock: Clock, account_id: uuid.UUID) -> AccountEvidence:
    _require(actor, Capability.READ)
    account = _account(db, actor, account_id)
    now = clock.now()
    aliases = list(
        db.scalars(
            select(AccountAlias.normalized_name)
            .where(AccountAlias.organization_id == actor.organization_id, AccountAlias.account_id == account.id)
            .order_by(AccountAlias.normalized_name)
        )
    )
    rows = db.execute(
        select(AccountFact, SourceRecord)
        .outerjoin(
            SourceRecord,
            (SourceRecord.id == AccountFact.source_record_id)
            & (SourceRecord.organization_id == AccountFact.organization_id),
        )
        .where(AccountFact.organization_id == actor.organization_id, AccountFact.account_id == account.id)
        .order_by(AccountFact.claim_type, AccountFact.observed_at.desc())
    ).all()
    successors = {fact.supersedes_fact_id: fact.id for fact, _ in rows if fact.supersedes_fact_id is not None}
    facts = []
    for fact, source in rows:
        expired = [t for t in (fact.expires_at, source.expires_at if source else None) if t is not None]
        facts.append(
            FactView(
                id=fact.id,
                claim_type=fact.claim_type,
                value=dict(fact.typed_value_json),
                confidence_label=fact.confidence_label,
                verification_status=fact.verification_status,
                observed_at=fact.observed_at,
                evidence_excerpt=fact.evidence_excerpt,
                source=SourceView(
                    id=source.id,
                    provider=source.provider,
                    source_url=source.source_url,
                    permitted_storage_class=source.permitted_storage_class,
                    rights_policy_version=source.rights_policy_version,
                    observed_at=source.observed_at,
                    expires_at=source.expires_at,
                )
                if source
                else None,
                is_stale=any(t <= now for t in expired),
                expires_at=fact.expires_at,
                created_at=fact.created_at,
                recorded_by=fact.recorded_by,
                supersedes_fact_id=fact.supersedes_fact_id,
                superseded_by_fact_id=successors.get(fact.id),
                correction_reason=fact.correction_reason,
            )
        )
    return AccountEvidence(account=account, aliases=aliases, facts=facts)
