"""Account management (P1.4): list/detail/create/patch/archive, evidence entry, corrections.

Builds on the P1.2 services and their rights/claim rules. Every write is one
transaction that also appends an `action_audits` row; facts are append-only,
so a correction is a new fact linked to the one it corrects.
"""

import base64
import binascii
import hashlib
import json
import logging
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import select, tuple_, update
from sqlalchemy.orm import Session

from app.accounts import policy, service
from app.accounts.models import Account, AccountFact, AccountStatus, ActionAudit, SourceRecord
from app.auth.dependencies import Capability
from app.auth.service import Actor
from app.core.clock import Clock
from app.core.errors import Conflict, InvalidRequest, NotFound, Unprocessable
from app.core.request_context import current_request_id

logger = logging.getLogger("app.accounts")

DEFAULT_PAGE = 25
MAX_PAGE = 100
STALE_VERSION = "Account was changed by someone else; reload and retry"

# Manual lifecycle moves (blueprint §2). `excluded` is reached only through archive.
TRANSITIONS: dict[str, frozenset[str]] = {
    AccountStatus.DISCOVERED: frozenset({AccountStatus.RESEARCHING}),
    AccountStatus.RESEARCHING: frozenset({AccountStatus.ASSESSED, AccountStatus.DISCOVERED}),
    AccountStatus.ASSESSED: frozenset(
        {AccountStatus.SHORTLISTED, AccountStatus.INVESTIGATE, AccountStatus.NURTURE, AccountStatus.RESEARCHING}
    ),
    AccountStatus.SHORTLISTED: frozenset({AccountStatus.RESEARCHING, AccountStatus.INVESTIGATE, AccountStatus.NURTURE}),
    AccountStatus.INVESTIGATE: frozenset({AccountStatus.RESEARCHING, AccountStatus.SHORTLISTED, AccountStatus.NURTURE}),
    AccountStatus.NURTURE: frozenset({AccountStatus.RESEARCHING, AccountStatus.INVESTIGATE, AccountStatus.SHORTLISTED}),
    AccountStatus.EXCLUDED: frozenset(),
}


def _audit(
    db: Session,
    actor: Actor,
    clock: Clock,
    action: str,
    account_id: uuid.UUID,
    details: dict[str, Any],
    target_type: str = "account",
) -> None:
    db.add(
        ActionAudit(
            organization_id=actor.organization_id,
            actor_user_id=actor.user_id,
            action_type=action,
            target_type=target_type,
            target_id=account_id,
            details_json=details,
            request_id=current_request_id(),
            recorded_at=clock.now(),
        )
    )


# --- list with keyset cursor -------------------------------------------------------------------


@dataclass(frozen=True)
class AccountFilters:
    city: str | None = None
    vertical_id: uuid.UUID | None = None
    status: str | None = None
    q: str | None = None

    def digest(self, organization_id: uuid.UUID) -> str:
        """Binds a cursor to the caller's organization and exact filters."""
        raw = json.dumps(
            [str(organization_id), self.city, str(self.vertical_id) if self.vertical_id else None, self.status, self.q],
            separators=(",", ":"),
        )
        return hashlib.sha256(raw.encode()).hexdigest()[:32]


def encode_cursor(updated_at: datetime, account_id: uuid.UUID, filter_digest: str) -> str:
    raw = json.dumps({"v": 1, "u": updated_at.isoformat(), "i": str(account_id), "f": filter_digest})
    return base64.urlsafe_b64encode(raw.encode()).decode().rstrip("=")


def decode_cursor(cursor: str, filter_digest: str) -> tuple[datetime, uuid.UUID]:
    """Validated position token. Unsigned by design: it only addresses rows inside the
    caller's own organization-scoped, filtered result set (see account-management contract)."""
    if len(cursor) > 512:
        raise InvalidRequest("cursor is invalid")
    try:
        data = json.loads(base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4)))
        position = (datetime.fromisoformat(data["u"]), uuid.UUID(data["i"]))
        if data.get("v") != 1 or position[0].tzinfo is None:
            raise ValueError
        digest = data["f"]
    except (ValueError, KeyError, TypeError, binascii.Error, json.JSONDecodeError, UnicodeDecodeError):
        raise InvalidRequest("cursor is invalid") from None
    if digest != filter_digest:
        raise InvalidRequest("cursor does not match these filters; restart from the first page")
    return position


@dataclass(frozen=True)
class Page:
    accounts: list[Account]
    next_cursor: str | None


def list_accounts(
    db: Session, *, actor: Actor, filters: AccountFilters, limit: int = DEFAULT_PAGE, cursor: str | None = None
) -> Page:
    service._require(actor, Capability.READ)
    if not 1 <= limit <= MAX_PAGE:
        raise InvalidRequest(f"limit must be between 1 and {MAX_PAGE}")
    digest = filters.digest(actor.organization_id)
    query = select(Account).where(Account.organization_id == actor.organization_id)
    if filters.city:
        query = query.where(Account.city == filters.city)
    if filters.vertical_id:
        query = query.where(Account.vertical_id == filters.vertical_id)
    if filters.status:
        query = query.where(Account.status == filters.status)
    if filters.q:
        prefix = policy.normalize_name(filters.q)
        if not prefix:
            raise InvalidRequest("search text must contain letters or digits")
        escaped = prefix.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        query = query.where(Account.normalized_name.like(f"{escaped}%", escape="\\"))  # indexed prefix match
    if cursor:
        updated_at, account_id = decode_cursor(cursor, digest)
        query = query.where(tuple_(Account.updated_at, Account.id) < tuple_(updated_at, account_id))
    rows = list(db.scalars(query.order_by(Account.updated_at.desc(), Account.id.desc()).limit(limit + 1)))
    page, more = rows[:limit], len(rows) > limit
    next_cursor = encode_cursor(page[-1].updated_at, page[-1].id, digest) if more and page else None
    return Page(accounts=page, next_cursor=next_cursor)


# --- detail -------------------------------------------------------------------------------------


@dataclass(frozen=True)
class AccountDetail:
    evidence: service.AccountEvidence
    audits: list[ActionAudit]


def get_account(db: Session, *, actor: Actor, clock: Clock, account_id: uuid.UUID) -> AccountDetail:
    evidence = service.get_account_with_evidence(db, actor=actor, clock=clock, account_id=account_id)
    audits = list(
        db.scalars(
            select(ActionAudit)
            .where(
                ActionAudit.organization_id == actor.organization_id,
                ActionAudit.target_type == "account",
                ActionAudit.target_id == account_id,
            )
            .order_by(ActionAudit.recorded_at.desc(), ActionAudit.id)
            .limit(100)
        )
    )
    return AccountDetail(evidence=evidence, audits=audits)


# --- create / patch / archive ---------------------------------------------------------------------


def create(
    db: Session, *, actor: Actor, clock: Clock, vertical_id: uuid.UUID, name: str, city: str, locality: str | None
) -> Account:
    account = service.create_account(
        db, actor=actor, clock=clock, vertical_id=vertical_id, name=name, city=city, locality=locality, commit=False
    )
    _audit(db, actor, clock, "account.created", account.id, {"version": 1})
    db.commit()
    logger.info("account.created", extra={"context": {"account_id": str(account.id)}})
    return account


def _cas_update(
    db: Session, actor: Actor, clock: Clock, account_id: uuid.UUID, expected_version: int, values: dict[str, Any]
) -> Account:
    """Atomic compare-and-swap on `version`; 0 rows means stale (409) or not visible (404)."""
    result = db.execute(
        update(Account)
        .where(
            Account.id == account_id,
            Account.organization_id == actor.organization_id,
            Account.version == expected_version,
        )
        .values(**values, version=Account.version + 1, updated_at=clock.now())
        .returning(Account.id)
        .execution_options(synchronize_session=False)
    )
    if result.scalar_one_or_none() is None:
        db.rollback()
        service._account(db, actor, account_id)  # raises NotFound for missing / other-org ids
        raise Conflict(STALE_VERSION)
    account = db.get(Account, account_id, populate_existing=True)
    if account is None:  # deleted between the update and the read; accounts have no delete API
        raise NotFound()
    return account


def patch(
    db: Session,
    *,
    actor: Actor,
    clock: Clock,
    account_id: uuid.UUID,
    expected_version: int,
    canonical_name: str | None = None,
    locality: str | None = None,
    status: str | None = None,
    clear_locality: bool = False,
) -> Account:
    service._require(actor, Capability.MUTATE)
    current = service._account(db, actor, account_id)
    if current.version != expected_version:
        db.rollback()
        raise Conflict(STALE_VERSION)
    values: dict[str, Any] = {}
    changes: dict[str, Any] = {}
    if canonical_name is not None:
        name = service._policy(policy.clean_text, canonical_name, "name", 250)
        values |= {"canonical_name": name, "normalized_name": policy.normalize_name(name)}
        changes["canonical_name"] = {"from": current.canonical_name, "to": name}
    if clear_locality or locality is not None:
        new_locality = None if clear_locality else service._policy(policy.clean_text, locality, "locality", 160)
        values["locality"] = new_locality
        changes["locality"] = {"from": current.locality, "to": new_locality}
    if status is not None and status != current.status:
        if status == AccountStatus.EXCLUDED:
            raise Unprocessable("use archive to exclude an account")
        if status not in TRANSITIONS.get(current.status, frozenset()):
            raise Unprocessable(f"status cannot change from {current.status} to {status}")
        values["status"] = status
        changes["status"] = {"from": current.status, "to": status}
    if not values:
        raise InvalidRequest("no changes requested")
    account = _cas_update(db, actor, clock, account_id, expected_version, values)
    _audit(db, actor, clock, "account.updated", account.id, {"version": account.version, "changes": changes})
    db.commit()
    logger.info("account.updated", extra={"context": {"account_id": str(account.id)}})
    return account


def archive(db: Session, *, actor: Actor, clock: Clock, account_id: uuid.UUID, expected_version: int) -> Account:
    service._require(actor, Capability.ADMINISTER)  # owner only
    current = service._account(db, actor, account_id)
    if current.status == AccountStatus.EXCLUDED:
        raise Conflict("Account is already archived")
    previous = current.status
    account = _cas_update(db, actor, clock, account_id, expected_version, {"status": AccountStatus.EXCLUDED})
    _audit(db, actor, clock, "account.archived", account.id, {"version": account.version, "from_status": previous})
    db.commit()
    logger.info("account.archived", extra={"context": {"account_id": str(account.id)}})
    return account


# --- evidence ----------------------------------------------------------------------------------------


@dataclass(frozen=True)
class NewSource:
    provider: str
    source_url: str
    storage_class: str
    observed_at: datetime
    external_key: str | None = None
    expires_at: datetime | None = None


@dataclass(frozen=True)
class FactInput:
    claim_type: str
    value: dict[str, Any]
    verification_status: str
    confidence_label: str
    observed_at: datetime
    expires_at: datetime | None = None
    evidence_excerpt: str | None = None
    source_id: uuid.UUID | None = None
    new_source: NewSource | None = None


def _resolve_source(db: Session, actor: Actor, clock: Clock, data: FactInput) -> uuid.UUID | None:
    if data.source_id is not None and data.new_source is not None:
        raise InvalidRequest("give either an existing source or a new source, not both")
    if data.new_source is None:
        return data.source_id
    # Manual evidence workflow: registers the URL/key as provenance only; nothing is fetched.
    source = service.add_source_record(
        db,
        actor=actor,
        clock=clock,
        provider=data.new_source.provider,
        source_url=data.new_source.source_url,
        observed_at=data.new_source.observed_at,
        storage_class=data.new_source.storage_class,
        rights_policy_version=policy.RIGHTS_POLICY_VERSION,
        external_key=data.new_source.external_key,
        expires_at=data.new_source.expires_at,
        commit=False,
    )
    return source.id


def _record_fact(
    db: Session,
    actor: Actor,
    clock: Clock,
    account_id: uuid.UUID,
    data: FactInput,
    supersedes: AccountFact | None = None,
    reason: str | None = None,
) -> AccountFact:
    source_id = _resolve_source(db, actor, clock, data)
    return service.add_account_fact(
        db,
        actor=actor,
        clock=clock,
        account_id=account_id,
        claim_type=data.claim_type,
        typed_value=data.value,
        confidence_label=data.confidence_label,
        verification_status=data.verification_status,
        observed_at=data.observed_at,
        source_record_id=source_id,
        expires_at=data.expires_at,
        evidence_excerpt=data.evidence_excerpt,
        recorded_by=actor.user_id,
        supersedes_fact_id=supersedes.id if supersedes else None,
        correction_reason=reason,
        commit=False,
    )


def add_fact(db: Session, *, actor: Actor, clock: Clock, account_id: uuid.UUID, data: FactInput) -> AccountFact:
    service._require(actor, Capability.MUTATE)
    fact = _record_fact(db, actor, clock, account_id, data)
    _audit(
        db,
        actor,
        clock,
        "account.fact_added",
        account_id,
        {
            "fact_id": str(fact.id),
            "claim_type": fact.claim_type,
            "verification_status": fact.verification_status,
            "source_id": str(fact.source_record_id) if fact.source_record_id else None,
        },
    )
    db.commit()
    logger.info("account.fact_added", extra={"context": {"account_id": str(account_id), "fact_id": str(fact.id)}})
    return fact


def correct_fact(
    db: Session,
    *,
    actor: Actor,
    clock: Clock,
    account_id: uuid.UUID,
    fact_id: uuid.UUID,
    reason: str,
    data: FactInput,
) -> AccountFact:
    service._require(actor, Capability.MUTATE)
    service._account(db, actor, account_id)
    prior = db.scalar(
        select(AccountFact)
        .where(
            AccountFact.id == fact_id,
            AccountFact.organization_id == actor.organization_id,
            AccountFact.account_id == account_id,
        )
        .with_for_update()  # serializes racing corrections of the same fact
    )
    if prior is None:
        db.rollback()
        raise NotFound()
    already = db.scalar(
        select(AccountFact.id).where(
            AccountFact.organization_id == actor.organization_id, AccountFact.supersedes_fact_id == prior.id
        )
    )
    if already is not None:
        db.rollback()
        raise Conflict("This fact was already corrected; correct its latest version")
    if data.claim_type != prior.claim_type:
        db.rollback()
        raise Unprocessable("a correction must keep the same claim type")
    reason = service._policy(policy.clean_text, reason, "reason", 1000)
    if len(reason) < 3:
        raise InvalidRequest("reason must be at least 3 characters")
    fact = _record_fact(db, actor, clock, account_id, data, supersedes=prior, reason=reason)
    _audit(
        db,
        actor,
        clock,
        "account.fact_corrected",
        account_id,
        {"fact_id": str(fact.id), "supersedes_fact_id": str(prior.id), "claim_type": fact.claim_type},
    )
    db.commit()
    logger.info("account.fact_corrected", extra={"context": {"account_id": str(account_id), "fact_id": str(fact.id)}})
    return fact


def source_summary(db: Session, actor: Actor, source_id: uuid.UUID) -> SourceRecord:
    return service._source(db, actor, source_id)
