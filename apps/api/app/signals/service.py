"""School operations brief generation and reads (P3.2, ADR-017).

Inputs are the account's **current** P1.4 facts (any verification status;
the rubric decides what may count) plus the number of reviewed P2.3 links.
Generation is idempotent per input digest, so a concurrent or replayed
request returns the same immutable snapshot. Reads compare the latest
snapshot with today's digest and flag `needs_reassessment` when facts were
added, corrected or rejected, or their source rights expired.
"""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import exists, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session, aliased

from app.accounts import management
from app.accounts import service as account_service
from app.accounts.models import Account, AccountFact, AccountStatus, SourceRecord
from app.auth.dependencies import Capability
from app.auth.service import Actor
from app.core.clock import Clock
from app.core.errors import Conflict, NotFound
from app.resolution.models import CandidateAccountLink
from app.signals import rubric
from app.signals.models import SchoolSignalSnapshot


def _source_join(org: uuid.UUID) -> Any:
    return (SourceRecord.organization_id == org) & (SourceRecord.id == AccountFact.source_record_id)


def _account(db: Session, org: uuid.UUID, account_id: uuid.UUID) -> Account:
    account = db.scalar(select(Account).where(Account.organization_id == org, Account.id == account_id))
    if account is None:
        raise NotFound()
    return account


def evidence(db: Session, org: uuid.UUID, account_id: uuid.UUID) -> tuple[list[rubric.EvidenceFact], int]:
    successor = aliased(AccountFact)
    rows = db.execute(
        select(AccountFact, SourceRecord)
        .outerjoin(SourceRecord, _source_join(org))
        .where(
            AccountFact.organization_id == org, AccountFact.account_id == account_id,
            ~exists().where(successor.organization_id == org, successor.supersedes_fact_id == AccountFact.id),
        )
    ).all()  # fmt: skip
    facts = [
        rubric.EvidenceFact(
            fact_id=str(fact.id), claim_type=fact.claim_type, value=fact.typed_value_json,
            verification_status=fact.verification_status, observed_at=fact.observed_at,
            source_id=str(source.id) if source else None, source_url=source.source_url if source else None,
            storage_class=source.permitted_storage_class if source else None,
            source_expires_at=source.expires_at if source else None,
        )
        for fact, source in rows
    ]  # fmt: skip
    links = int(
        db.scalar(
            select(func.count()).select_from(CandidateAccountLink).where(
                CandidateAccountLink.organization_id == org, CandidateAccountLink.account_id == account_id,
                CandidateAccountLink.unlinked_at.is_(None),
            )
        )
        or 0
    )  # fmt: skip
    return facts, links


def generate(db: Session, *, actor: Actor, clock: Clock, account_id: uuid.UUID) -> tuple[SchoolSignalSnapshot, bool]:
    account_service._require(actor, Capability.MUTATE)
    org = actor.organization_id
    account = _account(db, org, account_id)
    if account.status == AccountStatus.EXCLUDED:
        raise Conflict("archived accounts are not assessed")
    now = clock.now()
    facts, links = evidence(db, org, account_id)
    digest, inputs = rubric.input_digest(facts, now, links)
    brief = rubric.evaluate(facts, now, links)
    created = db.scalar(
        insert(SchoolSignalSnapshot)
        .values(id=uuid.uuid4(), organization_id=org, account_id=account_id, rubric_version=rubric.RUBRIC_VERSION,
                input_digest=digest, inputs_json=inputs, signals_json=brief, linked_listings=links,
                created_by=actor.user_id, created_at=now)
        .on_conflict_do_nothing(constraint="uq_signal_snapshots_input")
        .returning(SchoolSignalSnapshot.id)
    )  # fmt: skip
    if created is not None:
        management._audit(db, actor, clock, "account.school_signals_generated", account_id,
                          {"snapshot_id": str(created), "rubric_version": rubric.RUBRIC_VERSION,
                           "states": {k: v["state"] for k, v in brief["signals"].items()}})  # fmt: skip
    db.commit()
    snapshot = db.scalar(
        select(SchoolSignalSnapshot).where(
            SchoolSignalSnapshot.organization_id == org, SchoolSignalSnapshot.account_id == account_id,
            SchoolSignalSnapshot.rubric_version == rubric.RUBRIC_VERSION, SchoolSignalSnapshot.input_digest == digest,
        )
    )  # fmt: skip
    assert snapshot is not None  # noqa: S101  # inserted now or by the conflicting concurrent request
    return snapshot, created is not None


def _citations(db: Session, org: uuid.UUID, snapshot: SchoolSignalSnapshot, now: datetime) -> dict[str, Any]:
    ids = {uuid.UUID(i["fact_id"]) for i in snapshot.inputs_json}
    if not ids:
        return {}
    successor = aliased(AccountFact)
    rows = db.execute(
        select(AccountFact, SourceRecord, exists().where(successor.organization_id == org,
                                                         successor.supersedes_fact_id == AccountFact.id))
        .outerjoin(SourceRecord, _source_join(org))
        .where(AccountFact.organization_id == org, AccountFact.id.in_(ids))
    ).all()  # fmt: skip
    out: dict[str, Any] = {}
    for fact, source, superseded in rows:
        expired = bool(source and source.expires_at and source.expires_at <= now)
        out[str(fact.id)] = {
            "claim_type": fact.claim_type, "verification_status": fact.verification_status,
            "observed_at": fact.observed_at.isoformat(), "superseded": bool(superseded),
            "has_excerpt": fact.evidence_excerpt is not None,
            "source": None if source is None else {
                "provider": source.provider, "source_url": source.source_url,
                "storage_class": source.permitted_storage_class, "rights_policy_version": source.rights_policy_version,
                "expires_at": source.expires_at.isoformat() if source.expires_at else None, "expired": expired,
            },
        }  # fmt: skip
    return out


def snapshot_view(db: Session, snapshot: SchoolSignalSnapshot, now: datetime) -> dict[str, Any]:
    signals = snapshot.signals_json["signals"]
    return {
        "id": str(snapshot.id), "account_id": str(snapshot.account_id), "rubric_version": snapshot.rubric_version,
        "input_digest": snapshot.input_digest, "inputs": snapshot.inputs_json,
        "linked_listings": snapshot.linked_listings,
        # JSONB does not keep key order: always present the six keys in the rubric's canonical order.
        "signals": {k: signals[k] for k in rubric.KEYS if k in signals},
        "created_at": snapshot.created_at.isoformat(),
        "created_by": str(snapshot.created_by), "citations": _citations(db, snapshot.organization_id, snapshot, now),
        "ranking": None,  # deliberately absent: this brief never prioritises or qualifies a school
    }  # fmt: skip


def latest(db: Session, org: uuid.UUID, account_id: uuid.UUID, now: datetime) -> dict[str, Any]:
    _account(db, org, account_id)
    history = list(
        db.scalars(
            select(SchoolSignalSnapshot)
            .where(SchoolSignalSnapshot.organization_id == org, SchoolSignalSnapshot.account_id == account_id)
            .order_by(SchoolSignalSnapshot.created_at.desc(), SchoolSignalSnapshot.id.desc())
            .limit(20)
        )
    )
    facts, links = evidence(db, org, account_id)
    current_digest, _ = rubric.input_digest(facts, now, links)
    head = history[0] if history else None
    return {
        "latest": snapshot_view(db, head, now) if head else None,
        "needs_reassessment": (
            head is None or head.input_digest != current_digest or head.rubric_version != rubric.RUBRIC_VERSION
        ),
        "current_input_digest": current_digest,
        "history": [{"id": str(s.id), "created_at": s.created_at.isoformat(), "input_digest": s.input_digest,
                     "rubric_version": s.rubric_version} for s in history],
    }  # fmt: skip


def get_snapshot(db: Session, org: uuid.UUID, snapshot_id: uuid.UUID) -> SchoolSignalSnapshot:
    snapshot = db.scalar(
        select(SchoolSignalSnapshot).where(
            SchoolSignalSnapshot.organization_id == org, SchoolSignalSnapshot.id == snapshot_id
        )
    )
    if snapshot is None:
        raise NotFound()
    return snapshot
